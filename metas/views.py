# metas/views.py
from collections import deque
from types import SimpleNamespace

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.core.paginator import Paginator
from django.db import transaction

from core.utils import get_unidade_atual
from core.models import No
from atividades.models import Atividade

from .models import Meta, MetaAlocacao, ProgressoMeta
from .forms import MetaForm
from django.http import HttpResponseForbidden
from django.views.decorators.http import require_http_methods
from django.db.models.functions import ExtractYear

@login_required
def metas_unidade_view(request):
    unidade = get_unidade_atual(request)
    unidade_real = unidade
    if not unidade:
        messages.warning(request, "Selecione ou assuma uma unidade para visualizar e gerenciar metas.")
        unidade = SimpleNamespace(id=None, nome="Nao selecionada")
        alocacoes = MetaAlocacao.objects.none()
        atividade_filtrada = None
        return render(
            request,
            "metas/meta_lista.html",
            {
                "unidade": unidade,
                "alocacoes": alocacoes,
                "atividade_filtrada": None,
                "has_unidade": False,
            },
        )

    atividade_id = request.GET.get("atividade")

    alocacoes = (
        MetaAlocacao.objects.select_related("meta", "meta__atividade", "meta__unidade_criadora")
        .filter(unidade=unidade_real)
        .order_by("meta__data_limite", "meta__titulo")
    )

    atividade_filtrada = None
    if atividade_id:
        try:
            atividade_filtrada = Atividade.objects.get(pk=atividade_id)
        except Atividade.DoesNotExist:
            atividade_filtrada = None
        else:
            alocacoes = alocacoes.filter(meta__atividade_id=atividade_filtrada.id)

    return render(request, "metas/meta_lista.html", {
        "unidade": unidade,
        "alocacoes": alocacoes,
        "atividade_filtrada": atividade_filtrada,
        "has_unidade": True,
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

    return render(
        request,
        "metas/atividades_lista.html",
        {
            "unidade": unidade,
            "unidade_nome": getattr(unidade, "nome", "Não selecionada"),
            "atividades": page_obj.object_list,
            "page_obj": page_obj,
            "areas": Atividade.Area.choices,
            "area_selected": area,
            "q": q,
        },
    )

@login_required
def definir_meta_view(request, atividade_id):
    atividade = get_object_or_404(Atividade, id=atividade_id)
    unidade = get_unidade_atual(request)
    has_unidade = unidade is not None

    # Anos únicos baseados na data_limite
    anos_disponiveis = (
        Meta.objects.filter(atividade=atividade, data_limite__isnull=False)
        .annotate(ano=ExtractYear("data_limite"))
        .values_list("ano", flat=True)
        .distinct()
        .order_by("-ano")
    )

    ano_selecionado = request.GET.get("ano")
    status_selecionado = request.GET.get("status")

    metas_atividade = Meta.objects.filter(atividade=atividade)
    if ano_selecionado:
        metas_atividade = metas_atividade.filter(data_limite__year=ano_selecionado)
    metas_atividade = list(metas_atividade)
    if status_selecionado == "concluida":
        metas_atividade = [m for m in metas_atividade if m.concluida]
    elif status_selecionado == "atrasada":
        metas_atividade = [m for m in metas_atividade if m.atrasada and not m.concluida]
    elif status_selecionado == "andamento":
        metas_atividade = [m for m in metas_atividade if not m.atrasada and not m.concluida]

    # --- TRATAMENTO DE POST (CRIAR META) ---
    if request.method == "POST":
        if not has_unidade:
            messages.error(request, "Selecione ou assuma uma unidade antes de criar metas.")
            return redirect("metas:definir-meta", atividade_id=atividade_id)
        form = MetaForm(request.POST)
        if form.is_valid():
            meta = form.save(commit=False)
            # garanta os campos de vínculo:
            meta.atividade = atividade
            if unidade and hasattr(meta, "unidade_criadora_id"):
                meta.unidade_criadora = unidade
            if hasattr(meta, "criado_por_id"):
                meta.criado_por = request.user
            meta.save()
            messages.success(request, "Meta criada com sucesso. Agora atribua as unidades responsáveis.")
            return redirect("metas:atribuir-meta", meta_id=meta.id)
        else:
            messages.error(request, "Corrija os erros do formulário.")
    else:
        # GET: form vazio (sem expor 'atividade' no form)
        form = MetaForm()

    return render(request, "metas/definir_meta.html", {
        "atividade": atividade,
        "form": form,
        "metas_atividade": metas_atividade,
        "anos_disponiveis": anos_disponiveis,
        "ano_selecionado": ano_selecionado,
        "status_selecionado": status_selecionado,
        "can_create": has_unidade,
        "unidade_nome": getattr(unidade, "nome", "Não selecionada"),
    })

@login_required
def atribuir_meta_view(request, meta_id):
    """
    Tela / fluxo para criar/editar MetaAlocacao para as unidades filhas do usuário.
    Nesta versão:
    - cada 'nodo' (ex.: supervisor) aparece como primeira linha do seu grupo,
      seguido das unidades filhas (assim o supervisor pode receber alocação).
    - a própria unidade atual (ex.: gerente) é também adicionada como primeiro grupo,
      permitindo que o gerente receba a meta diretamente.
    """
    unidade = get_unidade_atual(request)
    if not unidade:
        messages.error(request, "Selecione ou assuma uma unidade antes de atribuir metas.")
        return redirect("metas:metas-unidade")

    meta = Meta.objects.filter(pk=meta_id).select_related("unidade_criadora", "atividade").first()
    if not meta:
        messages.error(request, "Meta não encontrada ou já foi removida.")
        return redirect("metas:metas-unidade")

    # montar grupos: filhos diretos da unidade atual (ex.: supervisores -> unidades)
    grupos = []
    filhos_diretos = No.objects.filter(parent=unidade).order_by("nome")
    unidades_atribuiveis = []
    unidades_vistas = set()

    def registrar_unidade(nodo):
        if nodo.id not in unidades_vistas:
            unidades_atribuiveis.append(nodo)
            unidades_vistas.add(nodo.id)

    def coletar_descendentes(raiz):
        resultado = []
        fila = deque([raiz])
        visitados = set()
        while fila:
            atual = fila.popleft()
            filhos = list(atual.filhos.all().order_by("nome"))
            for filho in filhos:
                if filho.id in visitados:
                    continue
                visitados.add(filho.id)
                resultado.append(filho)
                fila.append(filho)
        return resultado

    for nodo in filhos_diretos:
        descendentes = coletar_descendentes(nodo)
        unidades_do_grupo = [nodo] + descendentes if descendentes else [nodo]
        grupos.append((nodo, unidades_do_grupo))
        for unidade_do_grupo in unidades_do_grupo:
            registrar_unidade(unidade_do_grupo)

    if unidade:
        already_present = any(getattr(nodo, "pk", None) == getattr(unidade, "pk", None) for nodo, _ in grupos)
        if not already_present:
            grupos.insert(0, (unidade, [unidade]))
        registrar_unidade(unidade)

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
                "unidade_atual": unidade,  # <- aqui
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
@require_http_methods(["GET", "POST"])
def encerrar_meta_view(request, meta_id):
    """
    Exibe uma pagina de confirmacao para encerrar a meta selecionada.
    Segue o mesmo padrao visual usado para encerrar atividades em 'Minhas Metas'.
    """
    meta = get_object_or_404(
        Meta.objects.select_related("atividade", "unidade_criadora"),
        pk=meta_id,
    )
    unidade = get_unidade_atual(request)
    if not unidade:
        messages.error(request, "Selecione uma unidade antes de encerrar metas.")
        return redirect("core:dashboard")

    if meta.unidade_criadora_id != unidade.id and not request.user.is_superuser:
        messages.warning(request, "Voce nao tem permissao para encerrar esta meta.")
        return redirect("metas:metas-unidade")

    alocacoes = list(meta.alocacoes.select_related("unidade").order_by("unidade__nome"))
    alocacao_atual = next((a for a in alocacoes if a.unidade_id == unidade.id), None)
    executado_unidade = getattr(alocacao_atual, "realizado", 0) if alocacao_atual else 0
    alocado_unidade = getattr(alocacao_atual, "quantidade_alocada", 0) if alocacao_atual else 0

    from programar.models import ProgramacaoItem  # import local para evitar ciclos
    pendentes_qs = (
        ProgramacaoItem.objects
        .select_related("programacao", "veiculo")
        .filter(programacao__unidade_id=unidade.id, meta_id=meta.id, concluido=False)
        .order_by("programacao__data", "id")
    )
    pendentes_total = pendentes_qs.count()
    pendentes_preview_raw = list(pendentes_qs[:5])
    pendentes_preview = [
        {
            "id": pend.id,
            "data": getattr(getattr(pend, "programacao", None), "data", None),
            "veiculo": getattr(getattr(pend, "veiculo", None), "nome", "") or "",
        }
        for pend in pendentes_preview_raw
    ]
    pendentes_tem_mais = pendentes_total > len(pendentes_preview)

    next_url = (
        request.POST.get("next")
        or request.GET.get("next")
        or request.META.get("HTTP_REFERER")
        or reverse("metas:metas-unidade")
    )

    if request.method == "POST":
        encerrar_flag = (request.POST.get("encerrar") or "").strip().lower() in {"1", "true", "on", "sim"}
        confirmar_pendentes = (request.POST.get("confirmar_pendentes") or "").strip() == "1"
        if not encerrar_flag:
            messages.error(request, "Confirme o encerramento da meta antes de salvar.")
        elif pendentes_total > 0 and not confirmar_pendentes:
            messages.warning(request, "Existem atividades pendentes desta meta. Confirme se deseja encerrar mesmo assim.")
        else:
            if not meta.encerrada:
                meta.encerrada = True
                meta.save(update_fields=["encerrada"])
                messages.success(request, "Meta encerrada com sucesso.")
            else:
                messages.info(request, "Esta meta ja estava encerrada.")
            return redirect(next_url)
    else:
        confirmar_pendentes = False

    contexto = {
        "meta": meta,
        "unidade": unidade,
        "alocacoes": alocacoes,
        "alocacao_atual": alocacao_atual,
        "executado_unidade": executado_unidade,
        "alocado_unidade": alocado_unidade,
        "total_realizado": meta.realizado_total,
        "total_alocado": meta.alocado_total,
        "percentual_execucao": meta.percentual_execucao,
        "next": next_url,
        "pendentes_total": pendentes_total,
        "pendentes_preview": pendentes_preview,
        "pendentes_tem_mais": pendentes_tem_mais,
        "confirmar_pendentes_checked": confirmar_pendentes,
        "pendentes_confirmacao_obrigatoria": request.method == "POST" and pendentes_total > 0 and not confirmar_pendentes,
    }
    return render(request, "metas/encerrar_meta.html", contexto)


@login_required
@require_http_methods(["POST"])
def excluir_meta_view(request, meta_id):
    """
    Exclui uma meta e suas alocações.
    Apenas a unidade criadora da meta ou um superusuário podem excluir.
    """
    unidade = get_unidade_atual(request)
    try:
        meta = Meta.objects.select_related("unidade_criadora", "atividade").get(pk=meta_id)
    except Meta.DoesNotExist:
        messages.error(request, "Meta não encontrada ou já foi removida.")
        return redirect("metas:metas-unidade")
    next_url = (
        request.POST.get("next")
        or request.META.get("HTTP_REFERER")
        or reverse("metas:metas-unidade")
    )

    if not unidade:
        messages.error(request, "Selecione uma unidade antes de excluir metas.")
        return redirect(next_url)

    if meta.unidade_criadora_id != unidade.id and not request.user.is_superuser:
        messages.warning(request, "Você não tem permissão para excluir esta meta.")
        return redirect(next_url)

    # segurança: impedir exclusão se houver programação vinculada ou execução registrada
    from programar.models import ProgramacaoItem  # import local para evitar custos em módulo

    if ProgramacaoItem.objects.filter(meta=meta).exists():
        messages.error(
            request,
            "Meta não pode ser excluída: ela está vinculada à programação de atividades.",
        )
        return redirect(next_url)

    if ProgressoMeta.objects.filter(alocacao__meta=meta).exists():
        messages.error(
            request,
            "Meta não pode ser excluída porque já possui registros de execução.",
        )
        return redirect(next_url)

    titulo = meta.display_titulo
    meta.delete()
    messages.success(request, f"Meta '{titulo}' excluída com sucesso.")
    return redirect(next_url)


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

@login_required
def redistribuir_meta_view(request, meta_id, parent_aloc_id):
    """
    Redistribui uma MetaAlocacao (parent) para os filhos da unidade dona dessa alocacao.
    Só permite se a unidade atual for a mesma da alocacao (ou superuser).
    """
    unidade = get_unidade_atual(request)
    if not unidade:
        messages.error(request, "Selecione uma unidade antes de redistribuir metas.")
        return redirect("core:dashboard")

    meta = get_object_or_404(Meta, pk=meta_id)
    parent_aloc = get_object_or_404(MetaAlocacao.objects.select_related('unidade'), pk=parent_aloc_id, meta=meta)

    parent_unidade = parent_aloc.unidade

    # Permissão básica: só a unidade dona da alocação (ou superuser) pode redistribuir
    if unidade.id != parent_unidade.id and not request.user.is_superuser:
        return HttpResponseForbidden("Você não tem permissão para redistribuir esta alocação.")

    # filhos da unidade (destinos potenciais)
    filhos = list(parent_unidade.filhos.all().order_by("nome"))
    if not filhos:
        messages.info(request, "Esta unidade não possui filhos para redistribuir.")
        return redirect("metas:metas-unidade")

    # alocações já existentes que têm parent=parent_aloc
    child_alocs_qs = MetaAlocacao.objects.filter(meta=meta, parent=parent_aloc).select_related('unidade')
    child_alocs_map = {a.unidade_id: a for a in child_alocs_qs}
    existing_total = sum(a.quantidade_alocada for a in child_alocs_qs)  # já redistribuído

    if request.method == "POST":
        submitted = {}
        total_submitted = 0
        for f in filhos:
            raw_q = (request.POST.get(f"qty_child_{f.id}", "") or "").strip()
            raw_obs = (request.POST.get(f"obs_child_{f.id}", "") or "").strip()
            try:
                qty = int(raw_q) if raw_q != "" else 0
            except (ValueError, TypeError):
                qty = 0
            submitted[f.id] = {"qty": qty, "obs": raw_obs}
            total_submitted += qty

        # validação: não redistribuir mais do que o disponível no parent
        parent_available = parent_aloc.quantidade_alocada or 0
        if total_submitted > parent_available:
            messages.error(request,
                f"A soma das redistribuições ({total_submitted}) excede a alocação disponível ({parent_available}). Ajuste as quantidades.")
            # re-render com submitted values
            return render(request, "metas/redistribuir_meta.html", {
                "meta": meta,
                "parent_aloc": parent_aloc,
                "filhos": filhos,
                "submitted": submitted,
                "existing_total": existing_total,
                "parent_available": parent_available,
            })

        # aplicar alterações em transação: criar/atualizar/deletar child alocações com parent=parent_aloc
        created = updated = deleted = 0
        with transaction.atomic():
            for f in filhos:
                sub = submitted.get(f.id, {"qty": 0, "obs": ""})
                qty = sub["qty"]
                obs = sub["obs"] or ""
                existing = child_alocs_map.get(f.id)

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
                            unidade=f,
                            quantidade_alocada=qty,
                            parent=parent_aloc,
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
            messages.success(request, "Redistribuições: " + ", ".join(msg_parts) + ".")
        else:
            messages.info(request, "Nenhuma alteração nas redistribuições.")

        return redirect("metas:metas-unidade")

    # GET -> render do formulário com os valores atuais (usamos existing se não houver submitted)
    # preparar dados por filho
    filhos_data = []
    for f in filhos:
        existing = child_alocs_map.get(f.id)
        filhos_data.append({
            "unidade": f,
            "existing": existing,
            "existing_qty": existing.quantidade_alocada if existing else 0,
            "existing_obs": existing.observacao if existing else "",
        })

    parent_available = parent_aloc.quantidade_alocada or 0
    return render(request, "metas/redistribuir_meta.html", {
        "meta": meta,
        "parent_aloc": parent_aloc,
        "filhos": filhos_data,
        "existing_total": existing_total,
        "parent_available": parent_available,
    })

