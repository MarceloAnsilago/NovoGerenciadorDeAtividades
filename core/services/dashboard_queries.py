from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import List

from django.db.models import Count, Sum, Q, IntegerField, Value
from django.db.models.functions import Coalesce, TruncMonth, TruncWeek
from django.utils import timezone

from atividades.models import Atividade
from metas.models import Meta, ProgressoMeta
from plantao.models import SemanaServidor
from programar.models import ProgramacaoItem, ProgramacaoItemServidor
from servidores.models import Servidor


def _filter_by_scope(queryset, user):
    """
    Hook de escopo. Caso haja regras de filtragem por unidade/perfil,
    ajustar aqui. Por enquanto retorna queryset sem alteracoes.
    """
    return queryset


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


def get_dashboard_kpis(user) -> dict:
    metas = _filter_by_scope(Meta.objects.all(), user)
    total_metas = metas.count()
    metas_ativas = metas.filter(encerrada=False).count()
    metas_concluidas = metas.filter(encerrada=True).count()

    programacoes = _filter_by_scope(ProgramacaoItem.objects.all(), user)
    hoje = timezone.localdate()
    atividades_concluidas_hoje = programacoes.filter(
        concluido=True,
        concluido_em__date=hoje,
    ).count()

    servidores_qs = _filter_by_scope(Servidor.objects.all(), user)
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


def get_metas_por_unidade(user) -> dict:
    qs = (
        _filter_by_scope(Meta.objects.select_related("unidade_criadora"), user)
        .values("unidade_criadora__nome")
        .annotate(total=Count("id"))
        .order_by("-total", "unidade_criadora__nome")
    )

    labels = []
    data = []
    for item in qs:
        labels.append(item["unidade_criadora__nome"] or "Sem unidade")
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


def get_atividades_por_area(user) -> dict:
    area_labels = dict(Atividade.Area.choices)
    qs = (
        _filter_by_scope(Atividade.objects.all(), user)
        .values("area")
        .annotate(total=Count("id"))
        .order_by("-total")
    )

    labels = []
    data = []
    palette = ["#0d6efd", "#198754", "#ffc107", "#dc3545", "#6f42c1", "#20c997", "#0dcaf0"]

    for item in qs:
        labels.append(area_labels.get(item["area"], item["area"]))
        data.append(item["total"])

    background = [palette[i % len(palette)] for i in range(len(labels))]

    return {
        "labels": labels,
        "datasets": [
            {
                "label": "Atividades",
                "backgroundColor": background,
                "data": data,
            }
        ],
    }


def get_progresso_mensal(user) -> dict:
    months = _month_sequence()
    start_date = months[0]

    qs = (
        _filter_by_scope(ProgressoMeta.objects.all(), user)
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


def get_programacoes_status_mensal(user) -> dict:
    months = _month_sequence()
    start_date = months[0]
    tz = timezone.get_current_timezone()

    qs = (
        _filter_by_scope(ProgramacaoItem.objects.all(), user)
        .filter(
            criado_em__gte=timezone.make_aware(
                datetime.combine(start_date, time.min),
                tz,
            )
        )
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
    }


def get_plantao_heatmap(user) -> dict:
    weeks = _week_sequence()
    start_date = weeks[0]

    qs = (
        _filter_by_scope(SemanaServidor.objects.select_related("semana"), user)
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


def get_uso_veiculos(user) -> dict:
    qs = (
        _filter_by_scope(
            ProgramacaoItem.objects.select_related("veiculo").filter(veiculo__isnull=False),
            user,
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


def get_top_servidores(user, limit: int = 10) -> dict:
    qs = (
        _filter_by_scope(
            ProgramacaoItemServidor.objects.select_related("servidor"),
            user,
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
