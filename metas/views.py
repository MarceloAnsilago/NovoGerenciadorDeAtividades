# metas/views.py
from collections import deque, defaultdict, OrderedDict
from datetime import date
from types import SimpleNamespace

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum, Count
from django.core.paginator import Paginator
from django.db import transaction
from django.utils import timezone

from core.utils import get_unidade_atual
from core.models import No
from atividades.models import Area, Atividade

from .models import Meta, MetaAlocacao, ProgressoMeta
from programar.models import ProgramacaoItem
from .forms import MetaForm
from django.http import HttpResponseForbidden
from django.views.decorators.http import require_http_methods
from django.db.models.functions import ExtractYear

MONTH_NAMES_PT = (
    "Janeiro",
    "Fevereiro",
    "Março",
    "Abril",
    "Maio",
    "Junho",
    "Julho",
    "Agosto",
    "Setembro",
    "Outubro",
    "Novembro",
    "Dezembro",
)


def _build_month_filters(alocacoes):
    month_keys = OrderedDict()
    for aloc in alocacoes:
        meta_obj = getattr(aloc, "meta", None)
        if not meta_obj:
            continue
        limite = getattr(meta_obj, "data_limite", None)
        if limite and hasattr(limite, "date") and not isinstance(limite, date):
            limite = limite.date()
        if limite:
            key = f"{limite.year}-{limite.month:02d}"
            label = f"{MONTH_NAMES_PT[limite.month - 1]} de {limite.year}"
        else:
            key = "nodate"
            label = "Sem data"
        if key not in month_keys:
            month_keys[key] = label
        setattr(meta_obj, "month_key", key)

    return [{"key": key, "label": label} for key, label in month_keys.items()]

def _prepare_metas_context(request, *, emit_messages=False):
    today = timezone.localdate()
    unidade = get_unidade_atual(request)
    unidade_real = unidade
    if not unidade:
        if emit_messages:
            messages.warning(request, "Selecione ou assuma uma unidade para visualizar e gerenciar metas.")
        return {
            "unidade": SimpleNamespace(id=None, nome="Nao selecionada"),
            "alocacoes": MetaAlocacao.objects.none(),
            "atividade_filtrada": None,
            "has_unidade": False,
        }

    atividade_id = request.GET.get("atividade")
    area_code = (request.GET.get("area") or "").strip()
    status = (request.GET.get("status") or "").strip()

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

    # Filtro de área (permite navegar do dashboard)
    if area_code:
        if area_code == Area.CODE_ANIMAL:
            alocacoes = alocacoes.filter(
                Q(meta__atividade__area__code=Area.CODE_ANIMAL)
                | Q(meta__atividade__area__code=Area.CODE_ANIMAL_VEGETAL)
            )
        elif area_code == Area.CODE_VEGETAL:
            alocacoes = alocacoes.filter(
                Q(meta__atividade__area__code=Area.CODE_VEGETAL)
                | Q(meta__atividade__area__code=Area.CODE_ANIMAL_VEGETAL)
            )
        else:
            alocacoes = alocacoes.filter(meta__atividade__area__code=area_code)

    # Filtro de status (ativas/encerradas)
    if status == "ativas":
        alocacoes = alocacoes.filter(meta__encerrada=False)
    elif status == "encerradas":
        alocacoes = alocacoes.filter(meta__encerrada=True)

    alocacoes = list(alocacoes)

    # Inclui metas criadas na unidade atual sem qualquer alocacao.
    metas_sem_aloc = (
        Meta.objects.select_related("atividade", "unidade_criadora")
        .filter(unidade_criadora=unidade_real, alocacoes__isnull=True)
        .order_by("data_limite", "titulo")
    )
    if atividade_filtrada:
        metas_sem_aloc = metas_sem_aloc.filter(atividade_id=atividade_filtrada.id)

    if area_code:
        if area_code == Area.CODE_ANIMAL:
            metas_sem_aloc = metas_sem_aloc.filter(
                Q(atividade__area__code=Area.CODE_ANIMAL)
                | Q(atividade__area__code=Area.CODE_ANIMAL_VEGETAL)
            )
        elif area_code == Area.CODE_VEGETAL:
            metas_sem_aloc = metas_sem_aloc.filter(
                Q(atividade__area__code=Area.CODE_VEGETAL)
                | Q(atividade__area__code=Area.CODE_ANIMAL_VEGETAL)
            )
        else:
            metas_sem_aloc = metas_sem_aloc.filter(atividade__area__code=area_code)

    if status == "ativas":
        metas_sem_aloc = metas_sem_aloc.filter(encerrada=False)
    elif status == "encerradas":
        metas_sem_aloc = metas_sem_aloc.filter(encerrada=True)

    for meta_obj in metas_sem_aloc:
        alocacoes.append(
            SimpleNamespace(
                id=None,
                meta=meta_obj,
                meta_id=meta_obj.id,
                unidade=unidade_real,
                unidade_id=getattr(unidade_real, "id", None),
                quantidade_alocada=0,
                realizado=0,
                percentual_execucao=0.0,
                parent_id=None,
                is_virtual=True,
            )
        )

    def _aloc_sort_key(aloc):
        meta_obj = getattr(aloc, "meta", None)
        limite = getattr(meta_obj, "data_limite", None)
        if limite and hasattr(limite, "date") and not isinstance(limite, date):
            limite = limite.date()
        titulo = ""
        if meta_obj:
            titulo = (
                (getattr(meta_obj, "display_titulo", None) or getattr(meta_obj, "titulo", "") or "")
                .strip()
                .lower()
            )
        return (limite is None, limite or date.max, titulo)

    alocacoes.sort(key=_aloc_sort_key)

    # total de programações (pendentes ou concluídas) por meta na unidade atual
    try:
        meta_ids = [getattr(aloc, "meta_id", None) for aloc in alocacoes if getattr(aloc, "meta_id", None)]
        prog_counts = (
            ProgramacaoItem.objects
            .filter(meta_id__in=meta_ids, programacao__unidade=unidade_real)
            .values("meta_id")
            .annotate(total=Count("id"))
        )
        prog_count_map = {row["meta_id"]: row["total"] for row in prog_counts}
    except Exception:
        prog_count_map = {}

    for aloc in alocacoes:
        prog_total = prog_count_map.get(getattr(aloc, "meta_id", None), 0)
        setattr(aloc, "programadas_total", prog_total)
        if getattr(aloc, "meta", None):
            setattr(aloc.meta, "programadas_total", prog_total)

    # anos disponíveis pelas datas limite
    years_set = set()
    for aloc in alocacoes:
        limite = getattr(getattr(aloc, "meta", None), "data_limite", None)
        if limite and hasattr(limite, "year"):
            years_set.add(limite.year)
    years = sorted(years_set, reverse=True)

    ano_raw = request.GET.get("ano")
    ano_selected = None
    if ano_raw:
        try:
            ano_selected = int(ano_raw)
        except (ValueError, TypeError):
            ano_selected = None
    if ano_selected is None and years:
        current_year = today.year
        ano_selected = current_year if current_year in years else years[0]

    if ano_selected:
        # Mantemos metas sem data_limite mesmo com filtro de ano para que não "sumam" da lista.
        alocacoes = [
            aloc for aloc in alocacoes
            if not getattr(getattr(aloc, "meta", None), "data_limite", None)
            or getattr(aloc.meta.data_limite, "year", None) == ano_selected
        ]

    meta_month_filters = _build_month_filters(alocacoes)
    month_keys_order = [m.get("key") for m in meta_month_filters if "key" in m]

    month_param = request.GET.get("month") or ""
    today_key = f"{today.year}-{today.month:02d}"
    month_default = ""
    if month_param and month_param in month_keys_order:
        month_default = month_param
    elif today_key in month_keys_order:
        month_default = today_key
    elif month_keys_order:
        month_default = month_keys_order[0]

    return {
        "unidade": unidade,
        "alocacoes": alocacoes,
        "atividade_filtrada": atividade_filtrada,
        "area_selected": area_code,
        "status_selected": status,
        "has_unidade": True,
        "meta_month_filters": meta_month_filters,
        "years": years,
        "ano_selected": ano_selected,
        "meta_month_default": month_default,
    }


@login_required
def metas_unidade_view(request):
    contexto = _prepare_metas_context(request, emit_messages=True)
    return render(request, "metas/meta_lista.html", contexto)


@login_required
def atividades_lista_view(request):
    unidade = get_unidade_atual(request)
    atividades = Atividade.objects.filter(ativo=True).order_by("titulo")

    if unidade:
        atividades = atividades.filter(unidade_origem=unidade)

    # Filtros GET
    area = (request.GET.get("area") or "").strip()
    q = (request.GET.get("q") or "").strip()

    # Filtro de área
    if area == Area.CODE_ANIMAL:
        atividades = atividades.filter(
            Q(area__code=Area.CODE_ANIMAL) | Q(area__code=Area.CODE_ANIMAL_VEGETAL)
        )
    elif area == Area.CODE_VEGETAL:
        atividades = atividades.filter(
            Q(area__code=Area.CODE_VEGETAL) | Q(area__code=Area.CODE_ANIMAL_VEGETAL)
        )
    elif area:
        atividades = atividades.filter(area__code=area)

    # Busca por título ou descrição
    if q:
        atividades = atividades.filter(Q(titulo__icontains=q) | Q(descricao__icontains=q))

    # paginação simples (opcional)
    paginator = Paginator(atividades, 20)
    page = request.GET.get("page")
    page_obj = paginator.get_page(page)

    metas_context = _prepare_metas_context(request, emit_messages=True)

    return render(
        request,
        "metas/atividades_lista.html",
        {
            "unidade": unidade,
            "unidade_nome": getattr(unidade, "nome", "Nao selecionada"),
            "atividades": page_obj.object_list,
            "page_obj": page_obj,
            "areas": Area.objects.filter(ativo=True).order_by("nome"),
            "area_selected": area,
            "q": q,
            "alocacoes": metas_context.get("alocacoes", []),
            "has_unidade": metas_context.get("has_unidade", True),
            "atividade_filtrada": metas_context.get("atividade_filtrada"),
            "meta_month_filters": metas_context.get("meta_month_filters", []),
            "years": metas_context.get("years", []),
            "ano_selected": metas_context.get("ano_selected"),
            "meta_month_default": metas_context.get("meta_month_default", ""),
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
    status_param = request.GET.get("status")
    if status_param is None:
        status_selecionado = "andamento"
    elif status_param in {"concluida", "atrasada", "andamento", ""}:
        status_selecionado = status_param
    else:
        status_selecionado = ""

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
        "unidade_nome": getattr(unidade, "nome", "Nao selecionada"),
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
    next_url_default = reverse("metas:metas-unidade")
    next_url = request.GET.get("next") or request.POST.get("next") or next_url_default
    unidade = get_unidade_atual(request)
    meta = get_object_or_404(Meta, pk=meta_id)

    # checagem de permissão básica
    if unidade and meta.unidade_criadora_id != unidade.id and not request.user.is_superuser:
        messages.warning(request, "Você só pode editar metas da unidade atual.")
        return redirect(next_url)

    # evita edicao de metas ja encerradas
    if meta.encerrada:
        messages.warning(request, "Esta meta já foi encerrada e não pode ser editada.")
        return redirect(next_url)

    # info somente leitura
    meta_alocado_total = meta.alocado_total or 0
    meta_programadas_total = ProgramacaoItem.objects.filter(meta=meta).count()

    def _build_form(data=None):
        f = MetaForm(data=data, instance=meta)
        # Em edição, data_limite passa a ser obrigatória e deve vir pré-preenchida com o valor atual.
        f.fields["data_limite"].required = True
        initial_date = getattr(meta, "data_limite", None)
        f.fields["data_limite"].initial = initial_date
        if data is None:
            # garante preenchimento no GET mesmo se o field initial for ignorado pelo widget
            f.initial["data_limite"] = initial_date
        return f

    if request.method == "POST":
        form = _build_form(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Meta atualizada com sucesso.")
            return redirect(next_url)
        else:
            messages.error(request, "Corrija os erros do formulário.")
    else:
        form = _build_form()

    return render(request, "metas/editar_meta.html", {
        "form": form,
        "meta": meta,
        "unidade": unidade,
        "back_url": next_url,
        "meta_alocado_total": meta_alocado_total,
        "meta_programadas_total": meta_programadas_total,
    })


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

    from programar.models import ProgramacaoItem  # import local para evitar custos em modulo

    atividades_qs = ProgramacaoItem.objects.filter(meta=meta)
    atividades_removidas = atividades_qs.count()

    with transaction.atomic():
        if atividades_removidas:
            atividades_qs.delete()

        titulo = meta.display_titulo
        meta.delete()

    mensagem = f"Meta '{titulo}' excluida com sucesso."
    if atividades_removidas:
        plural = 's' if atividades_removidas != 1 else ''
        verbo = 'foram' if atividades_removidas != 1 else 'foi'
        mensagem += (
            f" {atividades_removidas} atividade{plural} planejada{plural} {verbo} removida{plural}"
            " junto com as programacoes vinculadas."
        )
    mensagem += ' Todos os registros ligados a essa meta foram removidos em cascata.'
    messages.success(request, mensagem)
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



@login_required
def encerrar_meta_view(request, meta_id):
    unidade = get_unidade_atual(request)
    next_url_default = reverse("metas:metas-unidade")
    next_url = request.GET.get("next") or request.POST.get("next") or next_url_default

    if not unidade:
        messages.error(request, "Selecione ou assuma uma unidade antes de encerrar metas.")
        return redirect(next_url)

    meta = (
        Meta.objects
        .select_related("unidade_criadora", "atividade")
        .filter(pk=meta_id)
        .first()
    )
    if not meta:
        messages.error(request, "Meta nao encontrada ou ja foi removida.")
        return redirect(next_url)

    if meta.unidade_criadora_id != getattr(unidade, "id", None) and not request.user.is_superuser:
        messages.warning(request, "Voce nao tem permissao para encerrar esta meta.")
        return redirect(next_url)

    if meta.encerrada:
        messages.info(request, "Meta ja esta encerrada.")
        return redirect(next_url)

    from programar.models import ProgramacaoItem

    def _compute_aloc_tree():
        qs = (
            MetaAlocacao.objects
            .filter(meta=meta)
            .select_related("unidade", "parent")
            .annotate(realizado_total=Sum("progresso__quantidade"))
            .order_by("parent_id", "unidade__nome", "id")
        )
        children_map = defaultdict(list)
        for aloc in qs:
            children_map[aloc.parent_id].append(aloc)

        flat_nodes = []

        def build_tree(parent_id=None, depth=0):
            nodes = []
            for aloc in children_map.get(parent_id, []):
                realizado = aloc.realizado_total or 0
                quantidade = aloc.quantidade_alocada or 0
                saldo = quantidade - realizado
                if saldo < 0:
                    saldo = 0
                percentual = 0.0
                if quantidade:
                    percentual = min(100.0, (realizado / quantidade) * 100.0)
                node = {
                    "aloc": aloc,
                    "depth": depth,
                    "indent": depth * 20,
                    "realizado": realizado,
                    "saldo": saldo,
                    "percentual": percentual,
                }
                node["filhos"] = build_tree(aloc.id, depth + 1)
                node["has_children"] = bool(node["filhos"])
                flat_nodes.append(node)
                nodes.append(node)
            return nodes

        tree = build_tree()
        aloc_top_total = sum((node["aloc"].quantidade_alocada or 0) for node in tree)
        saldo_total = sum(node["saldo"] for node in flat_nodes)
        return qs, tree, aloc_top_total, saldo_total

    def _compute_state():
        aloc_qs, aloc_tree, aloc_top_total, saldo_total = _compute_aloc_tree()
        pendentes_qs = (
            ProgramacaoItem.objects
            .select_related("programacao", "programacao__unidade", "veiculo")
            .filter(meta_id=meta.id, concluido=False)
            .order_by("programacao__data", "id")
        )
        pendentes_total = pendentes_qs.count()
        preview_limit = 5
        pendentes_preview = []
        for pend in pendentes_qs[:preview_limit]:
            prog = getattr(pend, "programacao", None)
            unidade_nome = getattr(getattr(prog, "unidade", None), "nome", "")
            pendentes_preview.append({
                "id": pend.id,
                "data": getattr(prog, "data", None),
                "unidade": unidade_nome,
                "veiculo": getattr(getattr(pend, "veiculo", None), "nome", ""),
            })
        pendentes_tem_mais = pendentes_total > len(pendentes_preview)

        concluidos_total = (
            ProgramacaoItem.objects
            .filter(meta_id=meta.id, concluido=True)
            .count()
        )
        total_programados = pendentes_total + concluidos_total

        meta_realizado_total = meta.realizado_total
        meta_percentual = meta.percentual_execucao

        inconsistencias = []
        alvo = meta.quantidade_alvo or 0
        if alvo and meta_realizado_total < alvo:
            inconsistencias.append({
                "code": "execucao_incompleta",
                "message": f"Execucao registrada em {meta_realizado_total} de {alvo} ({meta_percentual:.1f}%).",
                "auto_fix": False,
            })
        if alvo and meta.alocado_total < alvo:
            inconsistencias.append({
                "code": "alocacao_incompleta",
                "message": f"Alocacao total ({meta.alocado_total}) inferior ao alvo ({alvo}).",
                "auto_fix": False,
            })
        if alvo and total_programados < alvo:
            inconsistencias.append({
                "code": "programacao_insuficiente",
                "message": f"Programadas {total_programados} atividade(s) para um alvo de {alvo}.",
                "auto_fix": False,
            })
        if pendentes_total:
            inconsistencias.append({
                "code": "pendencias_programacao",
                "message": f"Existem {pendentes_total} atividade(s) programada(s) ainda pendente(s).",
                "auto_fix": True,
            })

        state = {
            "aloc_tree": aloc_tree,
            "tem_alocacoes": bool(aloc_qs),
            "aloc_top_total": aloc_top_total,
            "saldo_total": saldo_total,
            "pendentes_total": pendentes_total,
            "pendentes_preview": pendentes_preview,
            "pendentes_tem_mais": pendentes_tem_mais,
            "meta_realizado_total": meta_realizado_total,
            "meta_percentual": meta_percentual,
            "meta_alvo": alvo,
            "meta_alocado_total": meta.alocado_total,
            "concluidos_total": concluidos_total,
            "total_programados": total_programados,
            "inconsistencias": inconsistencias,
        }
        return state, pendentes_qs

    state, pendentes_qs = _compute_state()

    encerrar_agora_checked = False
    confirmar_pendentes_checked = False
    resolver_pendentes_checked = False
    auto_resolvidos = 0
    auto_sem_alocacao = 0
    form_errors = {}

    if request.method == "POST":
        encerrar_agora_checked = (request.POST.get("encerrar_agora") or "").strip().lower() in {"1", "true", "on", "sim"}
        confirmar_pendentes_checked = (request.POST.get("confirmar_pendentes") or "").strip().lower() in {"1", "true", "on", "sim"}
        resolver_pendentes_checked = (request.POST.get("resolver_pendentes") or "").strip().lower() in {"1", "true", "on", "sim"}

        if resolver_pendentes_checked and state["pendentes_total"] > 0:
            pendentes_list = list(pendentes_qs)
            with transaction.atomic():
                for pend in pendentes_list:
                    prog = getattr(pend, "programacao", None)
                    unidade_id = getattr(prog, "unidade_id", None)
                    concluido_em = timezone.now()
                    observacao_original = (pend.observacao or "").strip()
                    nota_suffix = "Encerrado automaticamente ao encerrar a meta."
                    observacao_final = observacao_original
                    if nota_suffix not in observacao_original:
                        observacao_final = (observacao_original + " " + nota_suffix).strip()

                    ProgramacaoItem.objects.filter(pk=pend.pk).update(
                        concluido=True,
                        concluido_em=concluido_em,
                        concluido_por_id=getattr(request.user, "id", None),
                        observacao=observacao_final,
                    )
                    auto_resolvidos += 1

                    if unidade_id:
                        aloc = (
                            MetaAlocacao.objects
                            .filter(meta_id=meta.id, unidade_id=unidade_id)
                            .order_by("id")
                            .first()
                        )
                        if aloc:
                            ProgressoMeta.objects.create(
                                data=getattr(prog, "data", timezone.localdate()),
                                quantidade=1,
                                observacao="Encerramento automatico da meta",
                                alocacao=aloc,
                                registrado_por=request.user,
                            )
                        else:
                            auto_sem_alocacao += 1
                    else:
                        auto_sem_alocacao += 1

            meta.refresh_from_db()
            state, pendentes_qs = _compute_state()

        if not encerrar_agora_checked:
            form_errors["encerrar_agora"] = "Marque a confirmacao para encerrar a meta."

        if state["pendentes_total"] > 0 and not resolver_pendentes_checked and not confirmar_pendentes_checked:
            form_errors["confirmar_pendentes"] = "Confirme que deseja encerrar mesmo com atividades pendentes."

        if not form_errors:
            meta.encerrada = True
            meta.save(update_fields=["encerrada"])
            success_message = "Meta encerrada com sucesso."
            if auto_resolvidos:
                success_message += f" {auto_resolvidos} atividade(s) foram encerradas automaticamente."
                if auto_sem_alocacao:
                    success_message += f" {auto_sem_alocacao} registro(s) nao geraram progresso por falta de alocacao."
            messages.success(request, success_message)
            return redirect(next_url)

        messages.warning(request, "Revise as confirmacoes antes de encerrar a meta.")

    mostrar_confirmar_pendentes = state["pendentes_total"] > 0 and not resolver_pendentes_checked

    contexto = {
        "meta": meta,
        "unidade": unidade,
        "aloc_tree": state["aloc_tree"],
        "tem_alocacoes": state["tem_alocacoes"],
        "aloc_top_total": state["aloc_top_total"],
        "saldo_total": state["saldo_total"],
        "meta_alvo": state["meta_alvo"],
        "meta_realizado_total": state["meta_realizado_total"],
        "meta_percentual": state["meta_percentual"],
        "meta_alocado_total": state["meta_alocado_total"],
        "total_programados": state["total_programados"],
        "concluidos_total": state["concluidos_total"],
        "pendentes_total": state["pendentes_total"],
        "pendentes_preview": state["pendentes_preview"],
        "pendentes_tem_mais": state["pendentes_tem_mais"],
        "inconsistencias": state["inconsistencias"],
        "resolver_pendentes_checked": resolver_pendentes_checked,
        "encerrar_agora_checked": encerrar_agora_checked,
        "confirmar_pendentes_checked": confirmar_pendentes_checked,
        "mostrar_confirmar_pendentes": mostrar_confirmar_pendentes,
        "form_errors": form_errors,
        "next_url": next_url,
    }
    return render(request, "metas/encerrar_meta.html", contexto)
