from collections import defaultdict, OrderedDict
from datetime import date
from calendar import monthrange

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone
from django.conf import settings
from django.db.models import Sum, Count
from django.http import JsonResponse
from django.template.loader import render_to_string

from core.utils import get_unidade_atual
from metas.models import MetaAlocacao
from programar.models import Programacao, ProgramacaoItem, ProgramacaoItemServidor

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


def _parse_iso(value: str | None) -> date | None:
    if not value:
        return None
    try:
        year, month, day = map(int, value.split("-"))
        return date(year, month, day)
    except Exception:
        return None


def _meta_status_info(meta):
    if not meta:
        return "andamento", "Em andamento"
    try:
        if getattr(meta, "encerrada", False):
            return "encerrada", "Encerrada"
        if getattr(meta, "concluida", False):
            return "concluida", "Concluída"
    except Exception:
        pass
    return "andamento", "Em andamento"


@login_required
def minhas_metas_view(request):
    unidade = get_unidade_atual(request)
    if not unidade:
        messages.error(request, "Selecione uma unidade antes de ver as metas.")
        return redirect("core:dashboard")

    meta_filter_raw = request.GET.get("meta")
    meta_filter_id: int | None = None
    try:
        if meta_filter_raw:
            meta_candidate = int(meta_filter_raw)
            if meta_candidate > 0:
                meta_filter_id = meta_candidate
    except (TypeError, ValueError):
        meta_filter_id = None

    today = timezone.localdate()

    status_param = request.GET.get("status")
    status_value = (status_param or "").lower()
    if status_value not in {"concluidas", "pendentes"}:
        status_value = ""

    status_query_filter = status_value
    status_dropdown = status_value
    if status_param is None:
        status_query_filter = "pendentes"
        status_dropdown = "pendentes"

    alocacoes_qs = (
        MetaAlocacao.objects
        .select_related("meta", "meta__atividade", "meta__criado_por", "meta__unidade_criadora")
        .annotate(realizado_unidade=Sum("progresso__quantidade"))
        .filter(unidade=unidade, meta__encerrada=False)
        .order_by("meta__data_limite", "meta__titulo")
    )

    meta_ids = list(alocacoes_qs.values_list("meta_id", flat=True))
    programadas_por_meta: dict[int, int] = {}
    if meta_ids:
        itens_stats = (
            ProgramacaoItem.objects
            .filter(meta_id__in=meta_ids)
            .values("meta_id")
            .annotate(total=Count("id"))
        )
        programadas_por_meta = {
            int(row["meta_id"]): int(row.get("total") or 0)
            for row in itens_stats
        }

    alocacoes = list(alocacoes_qs)
    for aloc in alocacoes:
        meta_obj = getattr(aloc, "meta", None)
        if meta_obj and getattr(meta_obj, "id", None):
            setattr(meta_obj, "programadas_total", programadas_por_meta.get(int(meta_obj.id), 0))
            status_key, status_label = _meta_status_info(meta_obj)
            setattr(meta_obj, "status_key", status_key)
            setattr(meta_obj, "status_label", status_label)

    # anos disponíveis (baseados na data_limite)
    years_set: set[int] = set()
    for aloc in alocacoes:
        limite = getattr(getattr(aloc, "meta", None), "data_limite", None)
        if limite and hasattr(limite, "year"):
            years_set.add(limite.year)
    years = sorted(years_set, reverse=True)

    ano_raw = request.GET.get("ano")
    ano_selected: int | None = None
    if ano_raw:
        try:
            ano_selected = int(ano_raw)
        except (ValueError, TypeError):
            ano_selected = None
    if ano_selected is None and years:
        current_year = today.year
        ano_selected = current_year if current_year in years else years[0]

    if ano_selected:
        # Inclui metas sem data_limite mesmo quando um ano específico está selecionado.
        alocacoes = [
            aloc for aloc in alocacoes
            if not getattr(getattr(aloc, "meta", None), "data_limite", None)
            or getattr(aloc.meta.data_limite, "year", None) == ano_selected
        ]

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

    tem_filhos = unidade.filhos.exists()

    month_param = request.GET.get("month") or ""
    today_key = f"{today.year}-{today.month:02d}"
    month_default_key: str | None = None
    if month_param and month_param in month_keys:
        month_default_key = month_param
    elif today_key in month_keys:
        month_default_key = today_key
    elif month_keys:
        month_default_key = next(iter(month_keys))

    meta_month_filters = [{"key": key, "label": label} for key, label in month_keys.items()]

    default_start = today.replace(day=1)
    default_end = today.replace(day=monthrange(today.year, today.month)[1])
    if (not request.GET.get("start")) and (not request.GET.get("end")) and month_default_key and month_default_key not in {"nodate", today_key}:
        try:
            m_year, m_month = [int(part) for part in month_default_key.split("-")]
            default_start = date(m_year, m_month, 1)
            default_end = date(m_year, m_month, monthrange(m_year, m_month)[1])
        except Exception:
            pass

    start_qs = request.GET.get("start")
    end_qs = request.GET.get("end")

    dt_start = _parse_iso(start_qs) or default_start
    dt_end = _parse_iso(end_qs) or default_end
    if dt_end < dt_start:
        dt_end = dt_start

    progs_qs = Programacao.objects.filter(
        unidade_id=unidade.id,
        data__gte=dt_start,
        data__lte=dt_end,
    )

    expediente_meta_id = getattr(settings, "META_EXPEDIENTE_ID", None)

    itens_qs = (
        ProgramacaoItem.objects
        .select_related("programacao", "meta", "veiculo")
        .filter(programacao__in=progs_qs)
        .order_by("programacao__data", "id")
    )
    if expediente_meta_id:
        itens_qs = itens_qs.exclude(meta_id=expediente_meta_id)
    if meta_filter_id:
        itens_qs = itens_qs.filter(meta_id=meta_filter_id)
    if status_query_filter == "concluidas":
        itens_qs = itens_qs.filter(concluido=True)
    elif status_query_filter == "pendentes":
        itens_qs = itens_qs.filter(concluido=False)

    item_ids = list(itens_qs.values_list("id", flat=True))
    servidores_por_item: dict[int, list[str]] = defaultdict(list)
    if item_ids:
        links = (
            ProgramacaoItemServidor.objects
            .select_related("servidor")
            .filter(item_id__in=item_ids, servidor__ativo=True)
        )
        for link in links:
            servidor_nome = getattr(link.servidor, "nome", f"Servidor {link.servidor_id}")
            servidores_por_item[link.item_id].append(servidor_nome)

    andamento = []
    vistos = set()
    for item in itens_qs:
        if item.id in vistos:
            continue
        vistos.add(item.id)
        meta = getattr(item, "meta", None)
        programacao = getattr(item, "programacao", None)
        if not meta or not programacao:
            continue

        andamento.append({
            "item_id": item.id,
            "data": getattr(programacao, "data", None),
            "meta_id": getattr(meta, "id", None),
            "meta_titulo": getattr(meta, "display_titulo", None) or getattr(meta, "titulo", "(sem titulo)"),
            "atividade_nome": getattr(getattr(meta, "atividade", None), "titulo", None),
            "veiculo": getattr(getattr(item, "veiculo", None), "nome", "") or "",
            "servidores": servidores_por_item.get(item.id, []),
            "concluido": bool(getattr(item, "concluido", False)),
        })

    selected_meta_title: str = ""
    selected_meta = None
    if meta_filter_id:
        for aloc in alocacoes:
            meta_obj = getattr(aloc, "meta", None)
            if meta_obj and getattr(meta_obj, "id", None) == meta_filter_id:
                selected_meta = meta_obj
                break
        if not selected_meta:
            selected_meta = MetaAlocacao.objects.filter(meta_id=meta_filter_id, unidade=unidade).select_related("meta").first()
            selected_meta = getattr(selected_meta, "meta", None)
        if selected_meta:
            selected_meta_title = getattr(selected_meta, "display_titulo", None) or getattr(selected_meta, "titulo", "")

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        html = render_to_string(
            "minhas_metas/partials/_andamento_rows.html",
            {"andamento": andamento},
            request=request,
        )
        return JsonResponse({
            "html": html,
            "meta": meta_filter_id or None,
            "meta_title": selected_meta_title,
        })

    contexto = {
        "unidade": unidade,
        "alocacoes": alocacoes,
        "tem_filhos": tem_filhos,
        "andamento": andamento,
        "dt_start": dt_start,
        "dt_end": dt_end,
        "status_filter": status_dropdown,
        "years": years,
        "ano_selected": ano_selected,
        "meta_filter_id": meta_filter_id or 0,
        "meta_filter_title": selected_meta_title,
        "meta_month_filters": meta_month_filters,
        "meta_month_default": month_default_key or "",
    }
    return render(request, "minhas_metas/lista_metas.html", contexto)
