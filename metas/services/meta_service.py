from __future__ import annotations

from typing import Iterable

from django.db import transaction
from django.db.models import Count, Max, Min, Q, QuerySet

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


def meta_esta_concluida(meta: Meta | None, *, unidade_id: int | None = None) -> bool:
    if meta is None:
        return False
    if meta.encerrada:
        return True

    alvo = int(meta.quantidade_alvo or 0)
    if unidade_id:
        alocacao = (
            meta.alocacoes
            .filter(unidade_id=unidade_id)
            .order_by("id")
            .first()
        )
        if alocacao:
            alvo = int(alocacao.quantidade_alocada or 0)
    if alvo <= 0:
        return False

    from programar.models import ProgramacaoItem

    itens_qs = ProgramacaoItem.objects.filter(meta_id=meta.id)
    if unidade_id:
        itens_qs = itens_qs.filter(programacao__unidade_id=unidade_id)

    solucionadas = itens_qs.filter(
        Q(concluido=True) | Q(nao_realizada_justificada=True)
    ).count()
    return solucionadas >= alvo


def resumo_execucao_meta(meta: Meta | None, *, unidade_id: int | None = None) -> dict:
    if meta is None:
        return {}

    alvo_meta = int(meta.quantidade_alvo or 0)
    alocado = 0
    alvo_referencia = alvo_meta
    if unidade_id:
        alocacao = (
            meta.alocacoes
            .filter(unidade_id=unidade_id)
            .order_by("id")
            .first()
        )
        if alocacao:
            alocado = int(alocacao.quantidade_alocada or 0)
            alvo_referencia = alocado
    if not alocado:
        alocado = int(meta.alocado_total or 0)

    from programar.models import ProgramacaoItem

    itens_qs = ProgramacaoItem.objects.filter(meta_id=meta.id)
    if unidade_id:
        itens_qs = itens_qs.filter(programacao__unidade_id=unidade_id)

    resumo = itens_qs.aggregate(
        programadas=Count("id"),
        concluidas=Count("id", filter=Q(concluido=True)),
        justificadas=Count("id", filter=Q(concluido=False, nao_realizada_justificada=True)),
        canceladas=Count("id", filter=Q(cancelada=True)),
        nao_realizadas=Count(
            "id",
            filter=Q(
                concluido=False,
                concluido_em__isnull=False,
                cancelada=False,
                nao_realizada_justificada=False,
            ),
        ),
        pendentes=Count(
            "id",
            filter=Q(
                concluido=False,
                concluido_em__isnull=True,
                cancelada=False,
                nao_realizada_justificada=False,
            ),
        ),
        primeira_data=Min("programacao__data"),
        ultima_data=Max("programacao__data"),
    )

    concluidas = int(resumo.get("concluidas") or 0)
    justificadas = int(resumo.get("justificadas") or 0)
    solucionadas = concluidas + justificadas
    percentual_solucionado = 0
    if alvo_referencia > 0:
        percentual_solucionado = min(100, round((solucionadas / alvo_referencia) * 100))

    resumo.update({
        "alvo_meta": alvo_meta,
        "alocado": alocado,
        "alvo_referencia": alvo_referencia,
        "solucionadas": solucionadas,
        "percentual_solucionado": percentual_solucionado,
    })
    return resumo


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
