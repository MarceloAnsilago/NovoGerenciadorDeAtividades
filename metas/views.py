# metas/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.core.paginator import Paginator
from django.db import transaction

from core.utils import get_unidade_atual
from core.models import No
from atividades.models import Atividade

from .models import Meta, MetaAlocacao
from .forms import MetaForm


@login_required
def metas_unidade_view(request):
    unidade = get_unidade_atual(request)
    if not unidade:
        messages.error(request, "Selecione uma unidade antes de ver as metas.")
        return redirect("core:dashboard")

    atividade_id = request.GET.get('atividade')

    # buscar alocações já relacionadas à unidade atual (com meta e atividade)
    alocacoes = (
        MetaAlocacao.objects.select_related('meta', 'meta__atividade')
        .filter(unidade=unidade)
        .order_by('meta__data_limite', 'meta__titulo')
    )

    if atividade_id:
        alocacoes = alocacoes.filter(meta__atividade__id=atividade_id)

    return render(request, 'metas/meta_lista.html', {
        'unidade': unidade,
        'alocacoes': alocacoes,
    })


@login_required
def atividades_lista_view(request):
    unidade = get_unidade_atual(request)
    atividades = Atividade.objects.filter(ativo=True).order_by('-criado_em')

    if unidade:
        atividades = atividades.filter(unidade_origem=unidade)

    # Filtros GET
    area = (request.GET.get("area") or "").strip()
    q = (request.GET.get("q") or "").strip()

    # Filtro de área
    if area == Atividade.Area.ANIMAL:
        atividades = atividades.filter(Q(area=Atividade.Area.ANIMAL) | Q(area=Atividade.Area.ANIMAL_VEGETAL))
    elif area == Atividade.Area.VEGETAL:
        atividades = atividades.filter(Q(area=Atividade.Area.VEGETAL) | Q(area=Atividade.Area.ANIMAL_VEGETAL))
    elif area:
        atividades = atividades.filter(area=area)

    # Busca por título ou descrição
    if q:
        atividades = atividades.filter(Q(titulo__icontains=q) | Q(descricao__icontains=q))

    # paginação simples (opcional)
    paginator = Paginator(atividades, 20)
    page = request.GET.get("page")
    page_obj = paginator.get_page(page)

    return render(request, "metas/atividades_lista.html", {
        "unidade": unidade,
        "atividades": page_obj.object_list,
        "page_obj": page_obj,
        "areas": Atividade.Area.choices,
        "area_selected": area,
        "q": q,
    })


@login_required
def definir_meta_view(request, atividade_id):
    unidade = get_unidade_atual(request)
    if not unidade:
        messages.error(request, "Selecione uma unidade antes de criar uma meta.")
        return redirect("core:dashboard")

    atividade = get_object_or_404(Atividade, pk=atividade_id)

    # Metas já criadas para esta atividade (lista para o card abaixo)
    metas_atividade = Meta.objects.filter(atividade=atividade).order_by("-criado_em")

    if request.method == "POST":
        form = MetaForm(request.POST)
        if form.is_valid():
            meta = form.save(commit=False)
            meta.atividade = atividade
            meta.unidade_criadora = unidade
            meta.criado_por = request.user
            meta.save()
            messages.success(request, "Meta criada com sucesso. Agora atribua quantidades.")
            return redirect("metas:atribuir-meta", meta_id=meta.id)
        else:
            messages.error(request, "Corrija os erros do formulário.")
    else:
        form = MetaForm()

    return render(request, "metas/definir_meta.html", {
        "atividade": atividade,
        "form": form,
        "unidade": unidade,
        "metas_atividade": metas_atividade,
    })


@login_required
def atribuir_meta_view(request, meta_id):
    """
    Tela / fluxo para criar/editar MetaAlocacao para as unidades filhas do usuário.
    """
    unidade = get_unidade_atual(request)
    if not unidade:
        messages.error(request, "Selecione uma unidade antes de atribuir metas.")
        return redirect("core:dashboard")

    meta = get_object_or_404(Meta, pk=meta_id)

    # montar grupos: filhos diretos da unidade atual (ex.: supervisores -> unidades)
    grupos = []
    filhos_diretos = No.objects.filter(parent=unidade).order_by("nome")
    unidades_atribuiveis = []

    for nodo in filhos_diretos:
        filhos = list(nodo.filhos.all().order_by("nome"))
        if filhos:
            grupos.append((nodo, filhos))
            unidades_atribuiveis.extend(filhos)
        else:
            grupos.append((nodo, [nodo]))
            unidades_atribuiveis.append(nodo)

    # se não tiver unidades atribuiveis, informar e redirecionar
    if not unidades_atribuiveis:
        messages.info(request, "Não há unidades filhas para atribuir metas a partir da unidade atual.")
        return redirect("metas:metas-unidade")

    # carregar alocações existentes apenas para as unidades exibidas
    unidades_pks = [u.pk for u in unidades_atribuiveis]
    aloc_qs = MetaAlocacao.objects.filter(meta=meta, unidade__in=unidades_pks).select_related('unidade')
    aloc_map = {a.unidade_id: a for a in aloc_qs}
    existing_for_units = sum(a.quantidade_alocada for a in aloc_qs)  # soma só p/ unidades da tela

    submitted_values = {}

    if request.method == "POST":
        total_submitted = 0
        for u in unidades_atribuiveis:
            raw_q = (request.POST.get(f"quantity_{u.id}", "") or "").strip()
            raw_obs = (request.POST.get(f"obs_{u.id}", "") or "").strip()
            try:
                qty = int(raw_q) if raw_q != "" else 0
            except (ValueError, TypeError):
                qty = 0
            submitted_values[u.id] = {"qty": qty, "obs": raw_obs}
            total_submitted += qty

        # validação de limite: substituímos existing_for_units pelas quantidades submetidas
        current_total_alocado = meta.alocado_total or 0
        current_for_units = existing_for_units
        new_total_alocado = current_total_alocado - current_for_units + total_submitted

        if meta.quantidade_alvo and meta.quantidade_alvo > 0 and new_total_alocado > meta.quantidade_alvo:
            messages.error(
                request,
                f"A soma das alocações ({new_total_alocado}) excede o alvo ({meta.quantidade_alvo}). Ajuste as quantidades."
            )

            # reconstroi grupos_with_data com submitted_values para re-render
            grupos_with_data = []
            for nodo, unidades in grupos:
                unidades_data = []
                for u in unidades:
                    aloc = aloc_map.get(u.id)
                    sub = submitted_values.get(u.id, {"qty": 0, "obs": ""})
                    unidades_data.append({
                        "unidade": u,
                        "alocacao": aloc,
                        "submitted_qty": sub["qty"],
                        "submitted_obs": sub["obs"],
                    })
                grupos_with_data.append((nodo, unidades_data))

            restante = meta.quantidade_alvo - meta.alocado_total if (meta.quantidade_alvo and meta.quantidade_alvo > 0) else None
            meta_info = {
                "meta_alvo": meta.quantidade_alvo or 0,
                "meta_alocado_total": meta.alocado_total or 0,
                "existing_for_units": existing_for_units,
            }

            return render(request, "metas/atribuir_meta.html", {
                "meta": meta,
                "unidade": unidade,
                "grupos_with_data": grupos_with_data,
                "meta_info": meta_info,
                "restante": restante,
            })

        # aplicar alterações (criar/atualizar/deletar) em transação
        created = updated = deleted = 0
        with transaction.atomic():
            for u in unidades_atribuiveis:
                sub = submitted_values.get(u.id, {"qty": 0, "obs": ""})
                qty = sub["qty"]
                obs = sub["obs"] or ""
                existing = aloc_map.get(u.id)

                if qty > 0:
                    if existing:
                        if existing.quantidade_alocada != qty or (existing.observacao or "") != obs:
                            existing.quantidade_alocada = qty
                            existing.observacao = obs
                            existing.save(update_fields=["quantidade_alocada", "observacao"])
                            updated += 1
                    else:
                        MetaAlocacao.objects.create(
                            meta=meta,
                            unidade=u,
                            quantidade_alocada=qty,
                            atribuida_por=request.user,
                            observacao=obs,
                        )
                        created += 1
                else:
                    if existing:
                        existing.delete()
                        deleted += 1

        msg_parts = []
        if created: msg_parts.append(f"{created} criada(s)")
        if updated: msg_parts.append(f"{updated} atualizada(s)")
        if deleted: msg_parts.append(f"{deleted} removida(s)")
        if msg_parts:
            messages.success(request, "Alocações: " + ", ".join(msg_parts) + ".")
        else:
            messages.info(request, "Nenhuma alteração realizada nas alocações.")

        return redirect("metas:metas-unidade")

    # GET -> montar grupos_with_data (pré-fill com alocações existentes)
    grupos_with_data = []
    for nodo, unidades in grupos:
        unidades_data = []
        for u in unidades:
            aloc = aloc_map.get(u.id)
            unidades_data.append({
                "unidade": u,
                "alocacao": aloc,
                "submitted_qty": None,
                "submitted_obs": None,
            })
        grupos_with_data.append((nodo, unidades_data))

    restante = meta.quantidade_alvo - meta.alocado_total if (meta.quantidade_alvo and meta.quantidade_alvo > 0) else None
    meta_info = {
        "meta_alvo": meta.quantidade_alvo or 0,
        "meta_alocado_total": meta.alocado_total or 0,
        "existing_for_units": existing_for_units,
    }

    return render(request, "metas/atribuir_meta.html", {
        "meta": meta,
        "unidade": unidade,
        "grupos_with_data": grupos_with_data,
        "meta_info": meta_info,
        "restante": restante,
    })


@login_required
def editar_meta_view(request, meta_id):
    """
    Edita os campos editáveis da Meta (data_limite, quantidade_alvo, descricao).
    Segurança simples: só permite editar se a unidade atual for a unidade_criadora
    ou se o usuário for superuser.
    """
    unidade = get_unidade_atual(request)
    meta = get_object_or_404(Meta, pk=meta_id)

    # checagem de permissão básica
    if unidade and meta.unidade_criadora_id != unidade.id and not request.user.is_superuser:
        messages.warning(request, "Você só pode editar metas da unidade atual.")
        return redirect("metas:metas-unidade")

    if request.method == "POST":
        form = MetaForm(request.POST, instance=meta)
        if form.is_valid():
            form.save()
            messages.success(request, "Meta atualizada com sucesso.")
            return redirect("metas:metas-unidade")
        else:
            messages.error(request, "Corrija os erros do formulário.")
    else:
        form = MetaForm(instance=meta)

    return render(request, "metas/editar_meta.html", {
        "form": form,
        "meta": meta,
        "unidade": unidade,
    })


@login_required
def toggle_encerrada_view(request, meta_id):
    """
    Alterna o campo 'encerrada' da Meta. Espera POST — se GET, redireciona.
    """
    if request.method != "POST":
        return redirect("metas:metas-unidade")

    meta = get_object_or_404(Meta, pk=meta_id)
    unidade = get_unidade_atual(request)

    # checagem de permissão básica
    if unidade and meta.unidade_criadora_id != unidade.id and not request.user.is_superuser:
        messages.warning(request, "Você não tem permissão para alterar esta meta.")
        return redirect("metas:metas-unidade")

    meta.encerrada = not meta.encerrada
    meta.save(update_fields=["encerrada"])
    messages.success(request, f"Meta {'encerrada' if meta.encerrada else 'reaberta'} com sucesso.")

    # tenta voltar para a página anterior
    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or "metas:metas-unidade"
    return redirect(next_url)
