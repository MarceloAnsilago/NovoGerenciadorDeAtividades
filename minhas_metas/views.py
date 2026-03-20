import json
from collections import defaultdict, OrderedDict
from datetime import date
from calendar import monthrange

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone
from django.conf import settings
from django.db.models import Sum, Count, Q
from django.db.models.functions import TruncMonth
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.urls import reverse

from core.utils import get_unidade_atual
from metas.models import MetaAlocacao
from programar.models import Programacao, ProgramacaoItem, ProgramacaoItemServidor
from programar.status import (
    ITEM_STATUS_LABELS,
    NAO_REALIZADA,
    NAO_REALIZADA_JUSTIFICADA,
    PENDENTE,
    REMARCADA_CONCLUIDA,
    EXECUTADA,
    item_execucao_status_from_fields,
)
from relatorios.services.non_performed_service import build_non_performed_groups
from veiculos.models import Veiculo

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


def _parse_month_key(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    raw = str(value).strip()
    try:
        year_str, month_str = raw.split("-")
        year = int(year_str)
        month = int(month_str)
    except Exception:
        return None
    if year < 1 or month < 1 or month > 12:
        return None
    return year, month


def _format_period_label(data_inicial: date | None, data_final: date | None) -> str:
    if not data_inicial or not data_final:
        return ""
    return f"{data_inicial.strftime('%d/%m/%Y')} -> {data_final.strftime('%d/%m/%Y')}"


def _build_programar_modal_context(unidade_id: int | None) -> dict[str, object]:
    veiculos_json = "[]"
    try:
        if unidade_id:
            veiculos_qs = (
                Veiculo.objects.filter(unidade_id=unidade_id, ativo=True)
                .order_by("nome")
                .values("id", "nome", "placa")
            )
            veiculos_json = json.dumps(list(veiculos_qs))
    except Exception:
        veiculos_json = "[]"
    return {
        "META_EXPEDIENTE_ID": getattr(settings, "META_EXPEDIENTE_ID", None),
        "VEICULOS_ATIVOS_JSON": veiculos_json,
    }


def _meta_status_info(meta):
    if not meta:
        return "andamento", "Em andamento"
    try:
        if getattr(meta, "encerrada", False):
            return "encerrada", "Encerrada"
        if getattr(meta, "concluida", False):
            return "concluida", "Concluída"
        if getattr(meta, "atrasada", False):
            return "atrasada", "Atrasada"
    except Exception:
        pass
    return "andamento", "Em andamento"


def _secondary_activity_name(meta) -> str | None:
    atividade = getattr(meta, "atividade", None)
    atividade_nome = getattr(atividade, "titulo", None) or getattr(atividade, "nome", None)
    atividade_nome = (str(atividade_nome).strip() if atividade_nome else "")
    if not atividade_nome:
        return None

    titulo_principal = getattr(meta, "display_titulo", None) or getattr(meta, "titulo", None)
    titulo_principal = (str(titulo_principal).strip() if titulo_principal else "")
    if titulo_principal and titulo_principal == atividade_nome:
        return None
    return atividade_nome


def _item_execucao_info(item):
    status = item_execucao_status_from_fields(
        bool(getattr(item, "concluido", False)),
        getattr(item, "concluido_em", None),
        bool(getattr(item, "nao_realizada_justificada", False)),
        getattr(item, "remarcado_de_id", None),
    )
    if status == REMARCADA_CONCLUIDA:
        return "remarcadas_concluidas", ITEM_STATUS_LABELS[REMARCADA_CONCLUIDA]
    if status == EXECUTADA:
        return "concluidas", ITEM_STATUS_LABELS[EXECUTADA]
    if status == NAO_REALIZADA_JUSTIFICADA:
        return "nao_realizadas_justificadas", "Não realizada justificada"
    if status == NAO_REALIZADA:
        return "nao_realizadas", "Não realizada"
    return "pendentes", ITEM_STATUS_LABELS[PENDENTE]


def _meta_ids_com_itens_abertos(
    unidade_id: int | None,
    *,
    reference_month_start: date | None = None,
) -> set[int]:
    if not unidade_id:
        return set()
    itens_qs = (
        ProgramacaoItem.objects
        .filter(
            programacao__unidade_id=unidade_id,
            concluido=False,
            nao_realizada_justificada=False,
            meta_id__isnull=False,
        )
    )
    if reference_month_start:
        itens_qs = itens_qs.filter(
            programacao__data__lt=reference_month_start,
            meta__data_limite__isnull=False,
            meta__data_limite__lt=reference_month_start,
        )
    ids = (
        itens_qs
        .values_list("meta_id", flat=True)
        .distinct()
    )
    return {int(meta_id) for meta_id in ids if meta_id}


@login_required
def minhas_metas_view(request, template_name="minhas_metas/lista_metas.html"):
    is_andamento_template = template_name == "minhas_metas/andamento_atividades.html"
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
    if is_andamento_template and not meta_filter_id:
        messages.info(request, "Selecione uma meta pela tela Minhas Metas para ver o andamento.")
        return redirect("minhas_metas:lista")

    today = timezone.localdate()
    month_param = (request.GET.get("month") or "").strip()
    month_param_parsed = _parse_month_key(month_param)
    ano_raw = request.GET.get("ano")
    status_month_start = (
        date(month_param_parsed[0], month_param_parsed[1], 1)
        if month_param_parsed
        else today.replace(day=1)
    )

    include_encerradas_cards = False
    if month_param_parsed:
        include_encerradas_cards = (month_param_parsed[0], month_param_parsed[1]) < (today.year, today.month)
    elif ano_raw:
        try:
            include_encerradas_cards = int(ano_raw) < today.year
        except (TypeError, ValueError):
            include_encerradas_cards = False

    status_param = request.GET.get("status")
    status_value = (status_param or "").lower()
    if status_value not in {"concluidas", "pendentes", "nao_realizadas", "nao_realizadas_justificadas", "remarcadas_concluidas"}:
        status_value = ""

    meta_status_cards_filter = (request.GET.get("meta_status") or "").strip().lower()
    if meta_status_cards_filter not in {"andamento", "atrasada", "concluida", "encerrada"}:
        meta_status_cards_filter = ""
    if meta_status_cards_filter == "encerrada":
        include_encerradas_cards = True

    status_query_filter = status_value
    status_dropdown = status_value
    if status_param is None:
        if is_andamento_template:
            status_query_filter = ""
            status_dropdown = ""
        else:
            status_query_filter = "pendentes"
            status_dropdown = "pendentes"

    alocacoes_qs = (
        MetaAlocacao.objects
        .select_related("meta", "meta__atividade", "meta__criado_por", "meta__unidade_criadora")
        .annotate(realizado_unidade=Sum("progresso__quantidade"))
        .filter(unidade=unidade)
        .order_by("meta__data_limite", "meta__titulo")
    )
    if not include_encerradas_cards:
        alocacoes_qs = alocacoes_qs.filter(meta__encerrada=False)

    meta_ids = list(alocacoes_qs.values_list("meta_id", flat=True))
    programadas_por_meta: dict[int, int] = {}
    metas_com_execucao_atrasada_ids: set[int] = set()
    if meta_ids:
        itens_stats = (
            ProgramacaoItem.objects
            .filter(meta_id__in=meta_ids, programacao__unidade_id=unidade.id)
            .values("meta_id")
            .annotate(
                total=Count("id"),
                nao_realizadas_atrasadas=Count(
                    "id",
                    filter=Q(
                        concluido=False,
                        concluido_em__isnull=False,
                        nao_realizada_justificada=False,
                        programacao__data__lt=status_month_start,
                        meta__data_limite__isnull=False,
                        meta__data_limite__lt=status_month_start,
                    ),
                ),
                pendentes_atrasadas=Count(
                    "id",
                    filter=Q(concluido=False, concluido_em__isnull=True, programacao__data__lt=today),
                ),
            )
        )
        for row in itens_stats:
            mid = int(row.get("meta_id") or 0)
            if not mid:
                continue
            programadas_por_meta[mid] = int(row.get("total") or 0)
            if int(row.get("nao_realizadas_atrasadas") or 0) > 0 or int(row.get("pendentes_atrasadas") or 0) > 0:
                metas_com_execucao_atrasada_ids.add(mid)

    metas_com_itens_abertos_ids = _meta_ids_com_itens_abertos(
        getattr(unidade, "id", None),
        reference_month_start=status_month_start,
    )

    alocacoes = list(alocacoes_qs)
    metas_sem_programacao = []
    metas_sem_programacao_ids = set()
    for aloc in alocacoes:
        meta_obj = getattr(aloc, "meta", None)
        if meta_obj and getattr(meta_obj, "id", None):
            meta_id_int = int(meta_obj.id)
            total_programadas = programadas_por_meta.get(meta_id_int, 0)
            setattr(meta_obj, "programadas_total", total_programadas)
            status_key, status_label = _meta_status_info(meta_obj)
            if status_key == "andamento" and meta_id_int in metas_com_execucao_atrasada_ids:
                status_key, status_label = "atrasada", "Atrasada"
            setattr(meta_obj, "status_key", status_key)
            setattr(meta_obj, "status_label", status_label)
            limite_meta = getattr(meta_obj, "data_limite", None)
            if limite_meta and hasattr(limite_meta, "date") and not isinstance(limite_meta, date):
                limite_meta = limite_meta.date()
            carry_forward = (
                bool(limite_meta)
                and limite_meta < status_month_start
                and meta_id_int in metas_com_itens_abertos_ids
            )
            setattr(meta_obj, "carry_forward", carry_forward)
            if (
                total_programadas == 0
                and (not meta_filter_id or meta_filter_id == meta_id_int)
                and meta_id_int not in metas_sem_programacao_ids
            ):
                metas_sem_programacao_ids.add(meta_id_int)
                metas_sem_programacao.append(meta_obj)

    # anos disponíveis (baseados na data_limite)
    years_set: set[int] = set()
    for aloc in alocacoes:
        limite = getattr(getattr(aloc, "meta", None), "data_limite", None)
        if limite and hasattr(limite, "year"):
            years_set.add(limite.year)
    if any(
        getattr(getattr(aloc, "meta", None), "carry_forward", False)
        and getattr(getattr(aloc, "meta", None), "data_limite", None)
        and getattr(getattr(aloc, "meta", None), "data_limite", None).year < today.year
        for aloc in alocacoes
    ):
        years_set.add(today.year)
    years = sorted(years_set, reverse=True)

    ano_selected: int | None = None
    if ano_raw:
        try:
            ano_selected = int(ano_raw)
        except (ValueError, TypeError):
            ano_selected = None
    if ano_selected is None and month_param_parsed:
        ano_selected = month_param_parsed[0]
    if ano_selected is None and years:
        current_year = today.year
        ano_selected = current_year if current_year in years else years[0]

    if ano_selected is not None and ano_selected not in years:
        years = sorted({*years, ano_selected}, reverse=True)

    if ano_selected:
        # Inclui metas sem data_limite e carrega pendentes/não realizadas de anos anteriores.
        filtradas = []
        for aloc in alocacoes:
            meta_obj = getattr(aloc, "meta", None)
            limite = getattr(meta_obj, "data_limite", None) if meta_obj else None
            if limite and hasattr(limite, "date") and not isinstance(limite, date):
                limite = limite.date()
            if not limite:
                filtradas.append(aloc)
                continue
            if limite.year == ano_selected:
                filtradas.append(aloc)
                continue
            if getattr(meta_obj, "carry_forward", False) and limite.year < ano_selected:
                filtradas.append(aloc)
        alocacoes = filtradas

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
        include_key = True
        parsed_key = _parse_month_key(key)
        if ano_selected is not None and key != "nodate":
            include_key = bool(parsed_key and parsed_key[0] == ano_selected)
        if include_key and key not in month_keys:
            month_keys[key] = label
        setattr(meta_obj, "month_key", key)

    today_key = f"{today.year}-{today.month:02d}"
    month_default_key: str | None = None
    if month_param_parsed:
        month_default_key = f"{month_param_parsed[0]}-{month_param_parsed[1]:02d}"
    elif today_key in month_keys:
        month_default_key = today_key
    elif month_keys:
        month_default_key = next(iter(month_keys))
    elif ano_selected:
        if ano_selected == today.year:
            month_default_key = today_key
        else:
            month_default_key = f"{ano_selected}-01"

    if month_default_key and month_default_key not in month_keys:
        parsed_default = _parse_month_key(month_default_key)
        if parsed_default:
            month_year, month_number = parsed_default
            month_label = f"{MONTH_NAMES_PT[month_number - 1]} de {month_year}"
            month_keys = OrderedDict([(month_default_key, month_label), *month_keys.items()])

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

    expediente_meta_id = getattr(settings, "META_EXPEDIENTE_ID", None)
    has_explicit_date = bool(start_qs or end_qs)
    usar_historico_completo_meta = bool(is_andamento_template and meta_filter_id and not has_explicit_date)

    itens_qs = (
        ProgramacaoItem.objects
        .select_related("programacao", "meta", "veiculo")
        .filter(programacao__unidade_id=unidade.id)
        .order_by("programacao__data", "id")
    )
    if not usar_historico_completo_meta:
        itens_qs = itens_qs.filter(
            programacao__data__gte=dt_start,
            programacao__data__lte=dt_end,
        )
    if expediente_meta_id:
        itens_qs = itens_qs.exclude(meta_id=expediente_meta_id)
    if meta_filter_id:
        itens_qs = itens_qs.filter(meta_id=meta_filter_id)
    if status_query_filter == "concluidas":
        itens_qs = itens_qs.filter(concluido=True)
    elif status_query_filter == "remarcadas_concluidas":
        itens_qs = itens_qs.filter(concluido=True, remarcado_de_id__isnull=False)
    elif status_query_filter == "nao_realizadas":
        itens_qs = itens_qs.filter(
            concluido=False,
            concluido_em__isnull=False,
            nao_realizada_justificada=False,
        )
    elif status_query_filter == "nao_realizadas_justificadas":
        itens_qs = itens_qs.filter(
            concluido=False,
            concluido_em__isnull=False,
            nao_realizada_justificada=True,
        )
    elif status_query_filter == "pendentes":
        itens_qs = itens_qs.filter(concluido=False, concluido_em__isnull=True)

    item_ids = list(itens_qs.values_list("id", flat=True))
    servidores_por_item: dict[int, list[str]] = defaultdict(list)
    if item_ids:
        links = (
            ProgramacaoItemServidor.objects
            .select_related("servidor")
            .filter(item_id__in=item_ids)
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

        status_key, status_label = _item_execucao_info(item)
        andamento.append({
            "item_id": item.id,
            "data": getattr(programacao, "data", None),
            "meta_id": getattr(meta, "id", None),
            "meta_titulo": getattr(meta, "display_titulo", None) or getattr(meta, "titulo", "(sem titulo)"),
            "atividade_nome": _secondary_activity_name(meta),
            "veiculo": getattr(getattr(item, "veiculo", None), "nome", "") or "",
            "servidores": servidores_por_item.get(item.id, []),
            "concluido": bool(getattr(item, "concluido", False)),
            "status_key": status_key,
            "status_label": status_label,
        })

    selected_meta_title: str = ""
    selected_meta = None
    selected_aloc = None
    if meta_filter_id:
        for aloc in alocacoes:
            meta_obj = getattr(aloc, "meta", None)
            if meta_obj and getattr(meta_obj, "id", None) == meta_filter_id:
                selected_meta = meta_obj
                selected_aloc = aloc
                break
        if not selected_meta:
            selected_aloc = MetaAlocacao.objects.filter(meta_id=meta_filter_id, unidade=unidade).select_related("meta").first()
            selected_meta = getattr(selected_aloc, "meta", None)
        if selected_meta:
            selected_meta_title = getattr(selected_meta, "display_titulo", None) or getattr(selected_meta, "titulo", "")

    resumo_meta = None
    if selected_meta and meta_filter_id:
        resumo_qs = ProgramacaoItem.objects.filter(
            programacao__unidade_id=unidade.id,
            meta_id=meta_filter_id,
        )
        if expediente_meta_id:
            resumo_qs = resumo_qs.exclude(meta_id=expediente_meta_id)

        resumo_agg = resumo_qs.aggregate(
            total=Count("id"),
            concluidas=Count("id", filter=Q(concluido=True)),
            remarcadas_concluidas=Count("id", filter=Q(concluido=True, remarcado_de_id__isnull=False)),
            nao_realizadas=Count(
                "id",
                filter=Q(
                    concluido=False,
                    concluido_em__isnull=False,
                    nao_realizada_justificada=False,
                ),
            ),
            nao_realizadas_justificadas=Count(
                "id",
                filter=Q(
                    concluido=False,
                    concluido_em__isnull=False,
                    nao_realizada_justificada=True,
                ),
            ),
            em_andamento=Count("id", filter=Q(concluido=False, concluido_em__isnull=True)),
            pendentes_atrasadas=Count(
                "id",
                filter=Q(concluido=False, concluido_em__isnull=True, programacao__data__lt=today),
            ),
        )

        total_programadas = int(resumo_agg.get("total") or 0)
        atividades_meta = int(getattr(selected_meta, "quantidade_alvo", 0) or 0)
        nao_programadas = max(atividades_meta - total_programadas, 0)
        concluidas = int(resumo_agg.get("concluidas") or 0)
        percentual_conclusao = round((concluidas / total_programadas) * 100, 1) if total_programadas else 0.0
        alocado_unidade = int(getattr(selected_aloc, "quantidade_alocada", 0) or 0)
        executado_unidade = int(getattr(selected_aloc, "realizado_unidade", 0) or 0)

        primeira_data = (
            resumo_qs.order_by("programacao__data")
            .values_list("programacao__data", flat=True)
            .first()
        )
        ultima_data = (
            resumo_qs.order_by("-programacao__data")
            .values_list("programacao__data", flat=True)
            .first()
        )

        resumo_meta = {
            "numero_atividades": atividades_meta,
            "data_inicio": getattr(selected_meta, "data_inicio", None),
            "data_final": getattr(selected_meta, "data_limite", None),
            "em_andamento": int(resumo_agg.get("em_andamento") or 0),
            "concluidas": concluidas,
            "remarcadas_concluidas": int(resumo_agg.get("remarcadas_concluidas") or 0),
            "nao_realizadas": int(resumo_agg.get("nao_realizadas") or 0),
            "nao_realizadas_justificadas": int(resumo_agg.get("nao_realizadas_justificadas") or 0),
            "em_programacao": total_programadas,
            "nao_programadas": nao_programadas,
            "pendentes_atrasadas": int(resumo_agg.get("pendentes_atrasadas") or 0),
            "percentual_conclusao": percentual_conclusao,
            "primeira_programacao": primeira_data,
            "ultima_programacao": ultima_data,
            "alocado_unidade": alocado_unidade,
            "executado_unidade": executado_unidade,
        }

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
        "andamento": andamento,
        "dt_start": dt_start,
        "dt_end": dt_end,
        "status_filter": status_dropdown,
        "meta_status_cards_filter": meta_status_cards_filter,
        "years": years,
        "ano_selected": ano_selected,
        "meta_filter_id": meta_filter_id or 0,
        "meta_filter_title": selected_meta_title,
        "meta_month_filters": meta_month_filters,
        "meta_month_default": month_default_key or "",
        "metas_sem_programacao": metas_sem_programacao,
        "resumo_meta": resumo_meta,
    }
    contexto.update(_build_programar_modal_context(unidade.id))
    contexto["META_EXPEDIENTE_ID"] = expediente_meta_id
    lista_base_url = reverse("minhas_metas:lista")
    query_string = request.GET.urlencode()
    contexto["back_to_metas_url"] = f"{lista_base_url}?{query_string}" if query_string else lista_base_url
    return render(request, template_name, contexto)


@login_required
def nao_realizadas_view(request):
    unidade = get_unidade_atual(request)
    if not unidade:
        messages.error(request, "Selecione uma unidade antes de ver as atividades não realizadas.")
        return redirect("core:dashboard")

    today = timezone.localdate()
    month_param = (request.GET.get("month") or "").strip()
    month_param_parsed = _parse_month_key(month_param)

    itens_base = (
        ProgramacaoItem.objects
        .select_related("programacao", "meta", "meta__atividade", "veiculo")
        .filter(
            programacao__unidade_id=unidade.id,
            concluido=False,
            concluido_em__isnull=False,
            nao_realizada_justificada=False,
        )
        .order_by("-programacao__data", "-id")
    )
    expediente_meta_id = getattr(settings, "META_EXPEDIENTE_ID", None)
    if expediente_meta_id:
        itens_base = itens_base.exclude(meta_id=expediente_meta_id)

    month_filters: list[dict[str, str | int]] = []
    month_counts_qs = (
        itens_base.exclude(programacao__data__isnull=True)
        .annotate(month_start=TruncMonth("programacao__data"))
        .values("month_start")
        .annotate(total=Count("id"))
        .order_by("-month_start")
    )
    for row in month_counts_qs:
        month_start = row.get("month_start")
        month_value = month_start.date() if hasattr(month_start, "date") else month_start
        if not month_value:
            continue
        month_key = f"{month_value.year}-{month_value.month:02d}"
        month_filters.append({
            "key": month_key,
            "label": f"{MONTH_NAMES_PT[month_value.month - 1]} de {month_value.year}",
            "total": int(row.get("total") or 0),
        })

    month_keys = [str(item.get("key") or "") for item in month_filters]
    selected_month_key = ""
    if month_param_parsed:
        candidate = f"{month_param_parsed[0]}-{month_param_parsed[1]:02d}"
        selected_month_key = candidate if candidate in month_keys else ""
    if not selected_month_key:
        today_key = f"{today.year}-{today.month:02d}"
        if today_key in month_keys:
            selected_month_key = today_key
        elif month_filters:
            selected_month_key = str(month_filters[0]["key"])

    is_print = request.GET.get("print", "").strip().lower() in {"1", "true", "yes", "on"}

    dt_start = None
    dt_end = None
    itens_qs = itens_base
    if selected_month_key:
        selected_parsed = _parse_month_key(selected_month_key)
        if selected_parsed:
            dt_start = date(selected_parsed[0], selected_parsed[1], 1)
            dt_end = date(
                selected_parsed[0],
                selected_parsed[1],
                monthrange(selected_parsed[0], selected_parsed[1])[1],
            )
            itens_qs = itens_qs.filter(programacao__data__gte=dt_start, programacao__data__lte=dt_end)

    item_ids = list(itens_qs.values_list("id", flat=True))
    servidores_por_item: dict[int, list[str]] = defaultdict(list)
    if item_ids:
        links = (
            ProgramacaoItemServidor.objects
            .select_related("servidor")
            .filter(item_id__in=item_ids)
            .order_by("servidor__nome")
        )
        for link in links:
            nome = getattr(getattr(link, "servidor", None), "nome", "") or f"Servidor {link.servidor_id}"
            servidores_por_item[link.item_id].append(nome)

    item_revisao_por_origem: dict[int, ProgramacaoItem] = {}
    if item_ids:
        itens_revisao_qs = (
            ProgramacaoItem.objects
            .select_related("programacao")
            .filter(
                programacao__unidade_id=unidade.id,
                remarcado_de_id__in=item_ids,
            )
            .order_by("-programacao__data", "-id")
        )
        for item_revisao in itens_revisao_qs:
            origem_id = getattr(item_revisao, "remarcado_de_id", None)
            if origem_id and origem_id not in item_revisao_por_origem:
                item_revisao_por_origem[origem_id] = item_revisao

    nao_realizadas = []
    for item in itens_qs:
        meta = getattr(item, "meta", None)
        programacao = getattr(item, "programacao", None)
        if not meta or not programacao:
            continue
        item_revisao = item_revisao_por_origem.get(item.id) or item
        nao_realizadas.append({
            "item_id": item.id,
            "review_item_id": getattr(item_revisao, "id", item.id),
            "data": getattr(programacao, "data", None),
            "meta_id": getattr(meta, "id", None),
            "meta_titulo": getattr(meta, "display_titulo", None) or getattr(meta, "titulo", "(sem titulo)"),
            "atividade_nome": _secondary_activity_name(meta),
            "servidores": servidores_por_item.get(item.id, []),
            "veiculo": getattr(getattr(item, "veiculo", None), "nome", "") or "",
            "observacao": (getattr(item, "observacao", "") or "").strip(),
            "concluido_em": getattr(item, "concluido_em", None),
        })

    nao_realizadas_grupos = []
    if dt_start and dt_end:
        nao_realizadas_grupos = build_non_performed_groups(
            unidade_id=unidade.id,
            data_inicial=dt_start,
            data_final=dt_end,
        )

    print_query = request.GET.copy()
    if selected_month_key:
        print_query["month"] = selected_month_key
    print_query["print"] = "1"

    contexto = {
        "unidade": unidade,
        "nao_realizadas": nao_realizadas,
        "nao_realizadas_grupos": nao_realizadas_grupos,
        "month_filters": month_filters,
        "selected_month_key": selected_month_key,
        "dt_start": dt_start,
        "dt_end": dt_end,
        "periodo_label": _format_period_label(dt_start, dt_end),
        "total_geral": itens_base.count(),
        "print_url": f"{reverse('minhas_metas:nao-realizadas')}?{print_query.urlencode()}",
    }
    contexto.update(_build_programar_modal_context(unidade.id))
    template_name = "minhas_metas/nao_realizadas_print.html" if is_print else "minhas_metas/nao_realizadas.html"
    return render(request, template_name, contexto)


@login_required
def andamento_atividades_view(request):
    return minhas_metas_view(request, template_name="minhas_metas/andamento_atividades.html")
