from __future__ import annotations

from typing import Iterable

from django.db import transaction
from django.db.models import Q, QuerySet

from metas.models import Meta
from metas.models import MetaAlocacao
from core.models import No


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


def unidade_tem_filhos(unidade: No | None) -> bool:
    if unidade is None or getattr(unidade, "pk", None) is None:
        return False
    return No.objects.filter(parent_id=unidade.id).exists()


def meta_deve_iniciar_automatica(unidade: No | None) -> bool:
    return not unidade_tem_filhos(unidade)


def get_auto_alocacao(meta: Meta) -> MetaAlocacao | None:
    return (
        meta.alocacoes
        .filter(unidade_id=meta.unidade_criadora_id, parent__isnull=True)
        .order_by("id")
        .first()
    )


def meta_auto_pode_ser_sincronizada(meta: Meta) -> bool:
    if not meta.is_auto_alocacao:
        return False
    auto_aloc = get_auto_alocacao(meta)
    if auto_aloc is None:
        return not meta.alocacoes.exists()
    return not meta.alocacoes.exclude(pk=auto_aloc.pk).exists()


@transaction.atomic
def sincronizar_meta_auto(meta: Meta, *, user) -> MetaAlocacao | None:
    if not meta.is_auto_alocacao:
        return None
    if not meta_auto_pode_ser_sincronizada(meta):
        raise ValueError("A meta automatica possui alocacoes extras e nao pode ser sincronizada automaticamente.")

    auto_aloc = get_auto_alocacao(meta)
    quantidade = int(meta.quantidade_alvo or 0)
    if quantidade <= 0:
        if auto_aloc:
            auto_aloc.delete()
        return None

    if auto_aloc:
        if auto_aloc.quantidade_alocada != quantidade:
            auto_aloc.quantidade_alocada = quantidade
            auto_aloc.save(update_fields=["quantidade_alocada"])
        return auto_aloc

    return MetaAlocacao.objects.create(
        meta=meta,
        unidade=meta.unidade_criadora,
        quantidade_alocada=quantidade,
        atribuida_por=user,
    )
