from __future__ import annotations

from datetime import date, timedelta
from typing import List

from django.conf import settings
from django.db.models import Count, Sum, Q, IntegerField, Value
from django.db.models.functions import Coalesce, TruncMonth, TruncWeek, ExtractYear, ExtractMonth
from django.utils import timezone

from atividades.models import Area, Atividade
from metas.models import Meta, MetaAlocacao, ProgressoMeta
from plantao.models import SemanaServidor
from programar.models import ProgramacaoItem, ProgramacaoItemServidor
from servidores.models import Servidor


def _filter_by_unidades(queryset, unidade_ids, field_lookup):
    """
    Aplica recorte por unidades de forma centralizada.
    - unidade_ids=None: n��o aplica filtro (escopo global).
    - unidade_ids vazio: retorna queryset vazio.
    - caso contr��rio: aplica filtro <field_lookup>__in=unidade_ids.
    """
    if unidade_ids is None:
        return queryset
    if not unidade_ids:
        return queryset.none()
    return queryset.filter(**{f"{field_lookup}__in": unidade_ids})


def _month_sequence(months: int = 12) -> List[date]:
    today = timezone.localdate()
    first_of_current = today.replace(day=1)
    year = first_of_current.year
    month = first_of_current.month
    sequence = []

    for _ in range(months):
        sequence.append(date(year, month, 1))
        month -= 1
        if month == 0:
            month = 12
            year -= 1

    sequence.reverse()
    return sequence


def _week_sequence(weeks: int = 12) -> List[date]:
    today = timezone.localdate()
    start_of_week = today - timedelta(days=today.weekday())
    sequence = []
    for i in range(weeks - 1, -1, -1):
        sequence.append(start_of_week - timedelta(days=i * 7))
    return sequence


def _month_sequence_for_range(start_date: date, end_date: date) -> List[date]:
    if start_date > end_date:
        return []
    start = start_date.replace(day=1)
    end = end_date.replace(day=1)
    months = []
    year = start.year
    month = start.month
    while (year, month) <= (end.year, end.month):
        months.append(date(year, month, 1))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return months


def _format_month_label_pt(month_date: date) -> str:
    month_names = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
    return f"{month_names[month_date.month - 1]}/{month_date.year}"


def _week_sequence_for_range(start_date: date, end_date: date) -> List[date]:
    if start_date > end_date:
        return []
    start_of_week = start_date - timedelta(days=start_date.weekday())
    end_of_week = end_date - timedelta(days=end_date.weekday())
    weeks = []
    current = start_of_week
    while current <= end_of_week:
        weeks.append(current)
        current += timedelta(days=7)
    return weeks


def _apply_date_range(queryset, field: str, start_date: date | None, end_date: date | None):
    if not start_date or not end_date:
        return queryset
    return queryset.filter(**{f"{field}__range": (start_date, end_date)})


def _base_programacao_items(unidade_ids=None):
    base_qs = _filter_by_unidades(
        ProgramacaoItem.objects.select_related("programacao", "meta"),
        unidade_ids,
        "programacao__unidade_id",
    )

    if unidade_ids is not None:
        if unidade_ids:
            base_qs = base_qs.filter(meta__alocacoes__unidade_id__in=unidade_ids)
        else:
            base_qs = base_qs.none()
    return base_qs


def get_dashboard_activity_filters(user, *, unidade_ids=None) -> dict:
    qs = (
        _filter_by_unidades(
            ProgramacaoItem.objects.select_related("programacao"),
            unidade_ids,
            "programacao__unidade_id",
        )
        .exclude(programacao__data__isnull=True)
        .annotate(ano=ExtractYear("programacao__data"), mes=ExtractMonth("programacao__data"))
        .values("ano", "mes")
        .distinct()
        .order_by("-ano", "-mes")
    )

    months_by_year: dict[str, list[int]] = {}
    for row in qs:
        ano = row.get("ano")
        mes = row.get("mes")
        if not ano or not mes:
            continue
        key = str(ano)
        months_by_year.setdefault(key, [])
        if mes not in months_by_year[key]:
            months_by_year[key].append(mes)

    for key in months_by_year:
        months_by_year[key].sort()

    years = sorted((int(y) for y in months_by_year.keys()), reverse=True)

    return {
        "years": years,
        "months_by_year": months_by_year,
    }


def get_dashboard_kpis(user, unidade_ids=None) -> dict:
    metas = _filter_by_unidades(Meta.objects.all(), unidade_ids, "alocacoes__unidade_id").distinct()
    total_metas = metas.count()
    metas_ativas = metas.filter(encerrada=False).count()
    metas_concluidas = metas.filter(encerrada=True).count()

    programacoes = _filter_by_unidades(
        ProgramacaoItem.objects.all(),
        unidade_ids,
        "programacao__unidade_id",
    )
    hoje = timezone.localdate()
    atividades_concluidas_hoje = programacoes.filter(
        concluido=True,
        concluido_em__date=hoje,
    ).count()

    servidores_qs = _filter_by_unidades(Servidor.objects.all(), unidade_ids, "unidade_id")
    servidores_ativos = servidores_qs.filter(ativo=True).count()

    percentual_concluidas = 0.0
    if total_metas:
        percentual_concluidas = round((metas_concluidas / total_metas) * 100, 2)

    return {
        "metas_ativas": metas_ativas,
        "percentual_metas_concluidas": percentual_concluidas,
        "atividades_concluidas_hoje": atividades_concluidas_hoje,
        "servidores_ativos": servidores_ativos,
    }


def get_metas_por_unidade(user, *, unidade_ids=None) -> dict:
    """
    Retorna o total de metas ativas por unidade considerando as alocações efetivas.
    - As metas encerradas são desconsideradas.
    - Quando unidade_ids é fornecido, limita o resultado às unidades informadas.
    """
    alocacoes = _filter_by_unidades(
        MetaAlocacao.objects.select_related("unidade", "meta"),
        unidade_ids,
        "unidade_id",
    )

    qs = (
        alocacoes.filter(meta__encerrada=False)
        .values("unidade__nome")
        .annotate(total=Count("meta", distinct=True))
        .order_by("-total", "unidade__nome")
    )

    labels = []
    data = []
    for item in qs:
        labels.append(item["unidade__nome"] or "Sem unidade")
        data.append(item["total"])

    return {
        "labels": labels,
        "datasets": [
            {
                "label": "Metas",
                "backgroundColor": "#0d6efd",
                "borderColor": "#0d6efd",
                "data": data,
            }
        ],
    }


def get_atividades_por_area(
    user,
    *,
    unidade_ids=None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    """
    Distribui por área as ATIVIDADES PROGRAMADAS (ProgramacaoItem),
    baseando-se na área da Atividade vinculada à Meta do item.

    - Escopo por unidade é aplicado via Programacao.unidade.
    - Itens cuja meta não possua atividade são classificados como OUTROS.
    """
    area_labels = {area.code: area.nome for area in Area.objects.all()}

    base_qs = _base_programacao_items(unidade_ids).select_related("meta__atividade", "programacao").filter(
        meta__encerrada=False
    )
    base_qs = _apply_date_range(base_qs, "programacao__data", start_date, end_date)

    qs = (
        base_qs
        .values("meta__atividade__area__code")
        .annotate(total=Count("id", distinct=True))
        .order_by("-total")
    )

    labels = []
    data = []
    codes = []
    palette = ["#0d6efd", "#198754", "#ffc107", "#dc3545", "#6f42c1", "#20c997", "#0dcaf0"]

    for item in qs:
        area_code = item.get("meta__atividade__area__code") or Area.CODE_OUTROS
        display_label = area_labels.get(area_code) or area_code.replace("_", " ").title()
        labels.append(display_label)
        data.append(item["total"])
        codes.append(area_code)

    background = [palette[i % len(palette)] for i in range(len(labels))]

    return {
        "labels": labels,
        "codes": codes,
        "datasets": [
            {
                "label": "Atividades programadas",
                "backgroundColor": background,
                "data": data,
            }
        ],
    }


def get_progresso_mensal(
    user,
    *,
    unidade_ids=None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    if start_date and end_date:
        months = _month_sequence_for_range(start_date, end_date)
    else:
        months = _month_sequence()
        start_date = months[0]

    qs = (
        _filter_by_unidades(ProgressoMeta.objects.all(), unidade_ids, "alocacao__unidade_id")
        .filter(data__gte=start_date)
        .annotate(mes=TruncMonth("data"))
        .values("mes")
        .annotate(total=Coalesce(Sum("quantidade"), Value(0), output_field=IntegerField()))
        .order_by("mes")
    )
    if start_date and end_date:
        qs = qs.filter(data__range=(start_date, end_date))

    mapped = {item["mes"]: item["total"] for item in qs if item["mes"] is not None}

    labels = []
    data = []
    for month_start in months:
        labels.append(_format_month_label_pt(month_start))
        data.append(mapped.get(month_start, 0))

    return {
        "labels": labels,
        "datasets": [
            {
                "label": "Progresso acumulado",
                "borderColor": "#6610f2",
                "backgroundColor": "rgba(102,16,242,0.2)",
                "tension": 0.3,
                "fill": True,
                "data": data,
            }
        ],
    }


def get_programacoes_status_mensal(
    user,
    *,
    unidade_ids=None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    if start_date and end_date:
        months = _month_sequence_for_range(start_date, end_date)
    else:
        months = _month_sequence()
        start_date = months[0]

    def _month_key(value):
        if value is None:
            return None
        to_date = getattr(value, "date", None)
        if callable(to_date):
            return to_date()
        return value

    base_qs = _base_programacao_items(unidade_ids).select_related("programacao", "meta")

    if start_date and end_date:
        base_qs = _apply_date_range(base_qs, "programacao__data", start_date, end_date)
    else:
        base_qs = base_qs.filter(programacao__data__gte=start_date)

    qs = (
        base_qs
        .annotate(mes=TruncMonth("programacao__data"))
        .values("mes")
        .annotate(
            concluidas=Count("id", filter=Q(concluido=True)),
            pendentes=Count("id", filter=Q(concluido=False)),
        )
        .order_by("mes")
    )

    concluidas_map = {}
    pendentes_map = {}
    for item in qs:
        mes_key = _month_key(item.get("mes"))
        if mes_key is None:
            continue
        concluidas_map[mes_key] = item.get("concluidas", 0)
        pendentes_map[mes_key] = item.get("pendentes", 0)

    labels = []
    concluidas_data = []
    pendentes_data = []

    for month_start in months:
        labels.append(_format_month_label_pt(month_start))
        concluidas_data.append(concluidas_map.get(month_start, 0))
        pendentes_data.append(pendentes_map.get(month_start, 0))

    # --- Hints por mes com a atividade (titulo) mais frequente por status ---
    hints_concluidas_map = {}
    hints_pendentes_map = {}
    detalhe_qs = (
        base_qs
        .annotate(mes=TruncMonth("programacao__data"))
        .values("mes", "concluido", "meta__atividade__titulo")
        .annotate(total=Count("id"))
        .order_by("mes", "-total")
    )
    for row in detalhe_qs:
        mes = row.get("mes")
        mes_key = _month_key(mes)
        if mes_key is None:
            continue
        titulo = row.get("meta__atividade__titulo") or "Outros"
        if row.get("concluido"):
            cur = hints_concluidas_map.get(mes_key) or []
            if titulo not in cur:
                cur.append(titulo)
                hints_concluidas_map[mes_key] = cur[:3]
        else:
            cur = hints_pendentes_map.get(mes_key) or []
            if titulo not in cur:
                cur.append(titulo)
                hints_pendentes_map[mes_key] = cur[:3]

    hints_concluidas = [", ".join(hints_concluidas_map.get(m, [])) for m in months]
    hints_pendentes = [", ".join(hints_pendentes_map.get(m, [])) for m in months]

    return {
        "labels": labels,
        "datasets": [
            {
                "label": "Concluidas",
                "backgroundColor": "#198754",
                "data": concluidas_data,
            },
            {
                "label": "Pendentes",
                "backgroundColor": "#dc3545",
                "data": pendentes_data,
            },
        ],
        "hints": {
            "concluidas": hints_concluidas,
            "pendentes": hints_pendentes,
        },
    }


def get_plantao_heatmap(
    user,
    *,
    unidade_ids=None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    if start_date and end_date:
        weeks = _week_sequence_for_range(start_date, end_date)
    else:
        weeks = _week_sequence()
        start_date = weeks[0]

    qs = (
        _filter_by_unidades(
            SemanaServidor.objects.select_related("semana", "servidor").filter(servidor__ativo=True),
            unidade_ids,
            "servidor__unidade_id",
        )
        .filter(semana__inicio__gte=start_date)
        .annotate(semana_inicio=TruncWeek("semana__inicio"))
        .values("semana_inicio")
        .annotate(total=Count("id"))
        .order_by("semana_inicio")
    )
    if start_date and end_date:
        qs = qs.filter(semana__inicio__range=(start_date, end_date))

    week_map = {
        item["semana_inicio"]: item["total"]
        for item in qs
        if item["semana_inicio"] is not None
    }

    labels = []
    data = []
    for start in weeks:
        labels.append(start.strftime("Semana %W/%Y"))
        data.append(week_map.get(start, 0))

    return {
        "labels": labels,
        "datasets": [
            {
                "label": "Servidores em plantao",
                "backgroundColor": "#20c997",
                "data": data,
            }
        ],
    }


def get_uso_veiculos(
    user,
    *,
    unidade_ids=None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    qs = (
        _filter_by_unidades(
            ProgramacaoItem.objects.select_related("veiculo").filter(veiculo__isnull=False),
            unidade_ids,
            "programacao__unidade_id",
        )
        .filter(**({"programacao__data__range": (start_date, end_date)} if start_date and end_date else {}))
        .values("veiculo__placa")
        .annotate(total=Count("id"))
        .order_by("-total", "veiculo__placa")[:10]
    )

    labels = []
    data = []
    for item in qs:
        labels.append(item["veiculo__placa"])
        data.append(item["total"])

    return {
        "labels": labels,
        "datasets": [
            {
                "label": "Programacoes",
                "backgroundColor": "#0dcaf0",
                "data": data,
            }
        ],
    }


def get_top_servidores(
    user,
    *,
    unidade_ids=None,
    limit: int = 10,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    meta_expediente_id = getattr(settings, "META_EXPEDIENTE_ID", None)
    try:
        meta_expediente_id = int(meta_expediente_id) if meta_expediente_id is not None else None
    except (TypeError, ValueError):
        meta_expediente_id = None

    base_qs = _filter_by_unidades(
        ProgramacaoItemServidor.objects.select_related(
            "servidor",
            "item__programacao",
            "item__meta",
        ).filter(servidor__ativo=True),
        unidade_ids,
        "item__programacao__unidade_id",
    )
    if start_date and end_date:
        base_qs = _apply_date_range(base_qs, "item__programacao__data", start_date, end_date)

    if meta_expediente_id:
        qs = (
            base_qs.values("servidor__nome")
            .annotate(
                total=Count("id"),
                expediente=Count("id", filter=Q(item__meta_id=meta_expediente_id)),
                campo=Count("id", filter=~Q(item__meta_id=meta_expediente_id)),
            )
            .order_by("-campo", "-expediente", "servidor__nome")
        )
    else:
        qs = (
            base_qs.values("servidor__nome")
            .annotate(
                total=Count("id"),
                expediente=Value(0, output_field=IntegerField()),
                campo=Count("id"),
            )
            .order_by("-campo", "servidor__nome")
        )

    qs = qs[:limit]

    labels: list[str] = []
    expediente_data: list[int] = []
    campo_data: list[int] = []
    for item in qs:
        nome = item["servidor__nome"] or "Servidor"
        labels.append(nome)
        expediente = int(item.get("expediente") or 0)
        campo = int(item.get("campo") or 0)
        expediente_data.append(expediente)
        campo_data.append(campo)

    # monta dicas com atividades de campo (top 3 por servidor)
    detail_map: dict[str, list[tuple[str, int]]] = {}
    campo_exists = meta_expediente_id is not None
    if campo_exists:
        detalhes_qs = (
            base_qs.exclude(item__meta_id=meta_expediente_id)
            .values("servidor__nome", "item__meta__titulo")
            .annotate(total=Count("id"))
            .order_by("servidor__nome", "-total", "item__meta__titulo")
        )
        for row in detalhes_qs:
            nome = row["servidor__nome"] or "Servidor"
            meta_titulo = row["item__meta__titulo"] or "Atividade"
            total = int(row.get("total") or 0)
            if total <= 0:
                continue
            detail_map.setdefault(nome, [])
            if len(detail_map[nome]) < 3:
                detail_map[nome].append((meta_titulo, total))

    hints: list[str] = []
    for idx, nome in enumerate(labels):
        expediente = expediente_data[idx] if idx < len(expediente_data) else 0
        campo = campo_data[idx] if idx < len(campo_data) else 0

        if campo_exists:
            if campo > 0:
                detalhes = detail_map.get(nome, [])
                if detalhes:
                    texto = ", ".join(f"{titulo} ({qt})" for titulo, qt in detalhes)
                    hints.append(f"Campo: {texto}")
                else:
                    hints.append("Campo: atividades diversas")
            else:
                hints.append("Somente expediente administrativo")
        else:
            hints.append("")

    datasets = []
    stack_name = None
    if meta_expediente_id and any(expediente_data):
        stack_name = "total"

    campo_dataset = {
        "label": "Atividades de campo",
        "backgroundColor": "#0d6efd",
        "data": campo_data,
    }
    if stack_name:
        campo_dataset["stack"] = stack_name

    datasets.append(campo_dataset)

    if stack_name:
        datasets.append(
            {
                "label": "Expediente administrativo",
                "backgroundColor": "#adb5bd",
                "data": expediente_data,
                "stack": stack_name,
            }
        )

    return {
        "labels": labels,
        "datasets": datasets,
        "hints": hints,
    }
