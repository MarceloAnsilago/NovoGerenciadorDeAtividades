from __future__ import annotations

from typing import Iterable

from django.db.models import Q, QuerySet

from metas.models import Meta


def metas_visiveis_por_unidade(unidade_id: int) -> QuerySet[Meta]:
    return Meta.objects.filter(
        Q(alocacoes__unidade_id=unidade_id) | Q(unidade_criadora_id=unidade_id)
    ).distinct()


def validar_meta_no_escopo(unidade_id: int, meta_id: int) -> bool:
    return metas_visiveis_por_unidade(unidade_id).filter(pk=meta_id).exists()


def filtrar_ids_no_escopo(unidade_id: int, meta_ids: Iterable[int]) -> set[int]:
    return set(
        metas_visiveis_por_unidade(unidade_id)
        .filter(pk__in=list(meta_ids))
        .values_list("id", flat=True)
    )
