# programar_atividades/services/plantao.py
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Tuple

from django.db.models import Prefetch, Q

from plantao.models import Plantao, Semana, SemanaServidor
from core.utils import get_unidade_atual_id


def _plantao_tem_unidade() -> bool:
    try:
        fields = [f.name for f in Plantao._meta.fields]
    except Exception:
        return False
    return "unidade" in fields or "unidade_id" in fields


def _get_accessor_semana_itens() -> str | None:
    """
    Descobre o accessor (related_name) do reverse Semana -> SemanaServidor.
    Retorna None se não encontrar algo válido (evita string vazia).
    """
    try:
        for f in Semana._meta.get_fields():
            if getattr(f, "is_relation", False) and getattr(f, "auto_created", False) and not getattr(f, "concrete", True):
                if getattr(f, "related_model", None) is SemanaServidor:
                    name = (f.get_accessor_name() or "").strip()
                    if name:
                        return name
    except Exception:
        pass
    return None


def _serialize_item(item) -> dict:
    srv = getattr(item, "servidor", None)
    nome = getattr(srv, "nome", "") if srv else ""
    telefone_snapshot = getattr(item, "telefone_snapshot", "") or ""
    tel_srv = getattr(srv, "telefone", "") if srv else ""
    cel_srv = getattr(srv, "celular", "") if srv else ""
    telefone_final = telefone_snapshot or tel_srv or cel_srv or ""
    return {
        "id": getattr(srv, "id", None),
        "nome": nome,
        "telefone": telefone_final,
        "ordem": getattr(item, "ordem", None),
    }


def _daterange(d0: date, d1: date):
    cur = d0
    while cur <= d1:
        yield cur
        cur += timedelta(days=1)


def _get_itens_qs(semana, accessor_hint: str | None = None):
    """
    Devolve QS de SemanaServidor para a 'semana', tolerante a qualquer related_name.
    """
    # 1) accessor sugerido
    if accessor_hint:
        rel = getattr(semana, accessor_hint, None)
        if rel is not None:
            try:
                return rel.all().select_related("servidor").order_by("ordem")
            except Exception:
                return rel.all().select_related("servidor")

    # 2) nomes comuns
    for name in ("itens", "semanaservidor_set"):
        rel = getattr(semana, name, None)
        if rel is not None:
            try:
                return rel.all().select_related("servidor").order_by("ordem")
            except Exception:
                return rel.all().select_related("servidor")

    # 3) fallback absoluto
    try:
        return SemanaServidor.objects.filter(semana=semana).select_related("servidor").order_by("ordem")
    except Exception:
        return SemanaServidor.objects.filter(semana=semana).select_related("servidor")


def get_plantonistas_por_periodo(
    dt_start: date,
    dt_end: date,
    *,
    unidade_id: int | None = None,
    apenas_titular: bool = False,
) -> Tuple[Dict[date, List[dict]], List[dict]]:
    """
    Retorna:
      - dias_map: { data -> [ {id, nome, telefone, ordem}, ... ] }
      - plantonistas_semana: lista única agregada no período.
    """
    accessor = _get_accessor_semana_itens()  # pode ser None

    semanas_qs = Semana.objects.filter(fim__gte=dt_start, inicio__lte=dt_end).select_related("plantao")
    if _plantao_tem_unidade() and unidade_id:
        semanas_qs = semanas_qs.filter(plantao__unidade_id=unidade_id)

    # Prefetch só se accessor for válido
    if accessor:
        try:
            prefetch = Prefetch(
                accessor,
                queryset=SemanaServidor.objects.select_related("servidor").order_by("ordem"),
                to_attr="__itens_prefetched",
            )
            semanas_qs = semanas_qs.prefetch_related(prefetch)
        except Exception:
            pass

    dias_map: Dict[date, List[dict]] = {}
    vistos = set()
    plantonistas_semana: List[dict] = []

    semanas_qs = semanas_qs.order_by("inicio")

    for semana in semanas_qs:
        itens = getattr(semana, "__itens_prefetched", None)
        if itens is None:
            itens = _get_itens_qs(semana, accessor_hint=accessor)

        if apenas_titular:
            try:
                itens = list(itens[:1])
            except TypeError:
                itens = list(itens)[:1]

        servidores = [_serialize_item(it) for it in itens]

        inter_ini = max(dt_start, semana.inicio)
        inter_fim = min(dt_end, semana.fim)
        for d in _daterange(inter_ini, inter_fim):
            dias_map[d] = servidores

        for s in servidores:
            key = (s.get("id"), s.get("nome"))
            if key not in vistos:
                vistos.add(key)
                plantonistas_semana.append(s)

    return dias_map, plantonistas_semana


def aplicar_plantonistas_na_semana_context(
    semana_list: List[dict],
    dt_start: date,
    dt_end: date,
    request=None,
    *,
    apenas_titular: bool = False,
) -> List[dict]:
    """
    Anota cada item de `semana_list` com `dia['plantonista'] = [...]`
    e retorna a lista `plantonistas_semana` única para o período.
    """
    unidade = get_unidade_atual_id(request) if request else None
    dias_map, plantonistas_semana = get_plantonistas_por_periodo(
        dt_start, dt_end, unidade_id=unidade, apenas_titular=apenas_titular
    )

    for dia in semana_list:
        data_obj = dia.get("data")
        if hasattr(data_obj, "date"):
            data_obj = data_obj.date()
        dia["plantonista"] = dias_map.get(data_obj, [])

    return plantonistas_semana
