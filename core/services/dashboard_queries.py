from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import List

from django.db.models import Count, Sum, Q, IntegerField, Value
from django.db.models.functions import Coalesce, TruncMonth, TruncWeek
from django.utils import timezone

from atividades.models import Atividade
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


def get_atividades_por_area(user, *, unidade_ids=None) -> dict:
    """
    Distribui por área as ATIVIDADES PROGRAMADAS (ProgramacaoItem),
    baseando-se na área da Atividade vinculada à Meta do item.

    - Escopo por unidade é aplicado via Programacao.unidade.
    - Itens cuja meta não possua atividade são classificados como OUTROS.
    """
    area_labels = dict(Atividade.Area.choices)

    base_qs = _filter_by_unidades(
        ProgramacaoItem.objects.select_related("meta__atividade", "programacao").filter(
            meta__encerrada=False
        ),
        unidade_ids,
        "programacao__unidade_id",
    )

    # Garante que a meta do item esta alocada para a(s) unidade(s) do escopo
    if unidade_ids is not None:
        if unidade_ids:
            base_qs = base_qs.filter(meta__alocacoes__unidade_id__in=unidade_ids)
        else:
            base_qs = base_qs.none()

    qs = (
        base_qs
        .values("meta__atividade__area")
        .annotate(total=Count("id", distinct=True))
        .order_by("-total")
    )

    labels = []
    data = []
    codes = []
    palette = ["#0d6efd", "#198754", "#ffc107", "#dc3545", "#6f42c1", "#20c997", "#0dcaf0"]

    for item in qs:
        area_code = item.get("meta__atividade__area") or Atividade.Area.OUTROS
        labels.append(area_labels.get(area_code, area_code))
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


def get_progresso_mensal(user, *, unidade_ids=None) -> dict:
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

    mapped = {item["mes"].date(): item["total"] for item in qs if item["mes"] is not None}

    labels = []
    data = []
    for month_start in months:
        labels.append(month_start.strftime("%b/%Y"))
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


def get_programacoes_status_mensal(user, *, unidade_ids=None) -> dict:
    months = _month_sequence()
    start_date = months[0]
    tz = timezone.get_current_timezone()

    base_qs = _filter_by_unidades(
        ProgramacaoItem.objects.select_related("programacao", "meta"),
        unidade_ids,
        "programacao__unidade_id",
    ).filter(
        criado_em__gte=timezone.make_aware(
            datetime.combine(start_date, time.min),
            tz,
        )
    )

    # Garante que as programações consideradas correspondem a metas alocadas
    if unidade_ids is not None:
        if unidade_ids:
            base_qs = base_qs.filter(meta__alocacoes__unidade_id__in=unidade_ids)
        else:
            base_qs = base_qs.none()

    qs = (
        base_qs
        .annotate(mes=TruncMonth("criado_em", tzinfo=tz))
        .values("mes")
        .annotate(
            concluidas=Count("id", filter=Q(concluido=True)),
            pendentes=Count("id", filter=Q(concluido=False)),
        )
        .order_by("mes")
    )

    concluidas_map = {item["mes"].date(): item["concluidas"] for item in qs if item["mes"] is not None}
    pendentes_map = {item["mes"].date(): item["pendentes"] for item in qs if item["mes"] is not None}

    labels = []
    concluidas_data = []
    pendentes_data = []

    for month_start in months:
        labels.append(month_start.strftime("%b/%Y"))
        concluidas_data.append(concluidas_map.get(month_start, 0))
        pendentes_data.append(pendentes_map.get(month_start, 0))

    # --- Hints por mes com a atividade (titulo) mais frequente por status ---
    hints_concluidas_map = {}
    hints_pendentes_map = {}
    detalhe_qs = (
        base_qs
        .annotate(mes=TruncMonth("criado_em", tzinfo=tz))
        .values("mes", "concluido", "meta__atividade__titulo")
        .annotate(total=Count("id"))
        .order_by("mes", "-total")
    )
    for row in detalhe_qs:
        mes = row.get("mes")
        if mes is None:
            continue
        mes_key = mes.date() if hasattr(mes, "date") else mes
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


def get_plantao_heatmap(user, *, unidade_ids=None) -> dict:
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

    week_map = {
        item["semana_inicio"].date(): item["total"]
        for item in qs
        if item["semana_inicio"] is not None
    }

    labels = []
    data = []
    for start in weeks:
        labels.append(start.strftime("Sem %W/%Y"))
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


def get_uso_veiculos(user, *, unidade_ids=None) -> dict:
    qs = (
        _filter_by_unidades(
            ProgramacaoItem.objects.select_related("veiculo").filter(veiculo__isnull=False),
            unidade_ids,
            "programacao__unidade_id",
        )
        .values("veiculo__nome")
        .annotate(total=Count("id"))
        .order_by("-total", "veiculo__nome")[:10]
    )

    labels = []
    data = []
    for item in qs:
        labels.append(item["veiculo__nome"])
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


def get_top_servidores(user, *, unidade_ids=None, limit: int = 10) -> dict:
    qs = (
        _filter_by_unidades(
            ProgramacaoItemServidor.objects.select_related("servidor", "item__programacao").filter(servidor__ativo=True),
            unidade_ids,
            "item__programacao__unidade_id",
        )
        .values("servidor__nome")
        .annotate(total=Count("id"))
        .order_by("-total", "servidor__nome")[:limit]
    )

    labels = []
    data = []
    for item in qs:
        labels.append(item["servidor__nome"])
        data.append(item["total"])

    return {
        "labels": labels,
        "datasets": [
            {
                "label": "Participacoes",
                "backgroundColor": "#6f42c1",
                "data": data,
            }
        ],
    }
