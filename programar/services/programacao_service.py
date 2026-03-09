from __future__ import annotations

from datetime import date
from typing import Any

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from metas.models import Meta
from programar.models import Programacao, ProgramacaoItem, ProgramacaoItemServidor
from programar.status import (
    EXECUTADA,
    NAO_REALIZADA,
    NAO_REALIZADA_JUSTIFICADA,
    PENDENTE,
    item_execucao_status_from_fields,
)
from servidores.models import Servidor
from veiculos.models import Veiculo


def _ids_permitidos(unidade_id: int) -> tuple[set[int], set[int], set[int]]:
    metas = set(
        Meta.objects.filter(
            Q(alocacoes__unidade_id=unidade_id) | Q(unidade_criadora_id=unidade_id)
        )
        .values_list("id", flat=True)
        .distinct()
    )
    servidores = set(
        Servidor.objects.filter(unidade_id=unidade_id, ativo=True).values_list("id", flat=True)
    )
    veiculos = set(
        Veiculo.objects.filter(unidade_id=unidade_id, ativo=True).values_list("id", flat=True)
    )
    return metas, servidores, veiculos


def get_programacao_dia(unidade_id: int, data_ref: date) -> list[dict[str, Any]]:
    prog = Programacao.objects.filter(unidade_id=unidade_id, data=data_ref).first()
    if not prog:
        return []

    itens = list(
        ProgramacaoItem.objects.filter(programacao_id=prog.id)
        .select_related("meta", "veiculo")
        .order_by("id")
    )
    item_ids = [item.id for item in itens]

    links = (
        ProgramacaoItemServidor.objects.select_related("servidor")
        .filter(item_id__in=item_ids)
        .order_by("item_id", "servidor__nome")
    )
    servidores_por_item: dict[int, list[dict[str, Any]]] = {}
    for link in links:
        servidores_por_item.setdefault(link.item_id, []).append(
            {"id": link.servidor_id, "nome": getattr(link.servidor, "nome", "")}
        )

    out: list[dict[str, Any]] = []
    for item in itens:
        meta = getattr(item, "meta", None)
        status_execucao = item_execucao_status_from_fields(
            bool(item.concluido),
            item.concluido_em,
            bool(getattr(item, "nao_realizada_justificada", False)),
        )
        out.append(
            {
                "id": item.id,
                "meta_id": item.meta_id,
                "titulo": getattr(meta, "display_titulo", None) or getattr(meta, "titulo", ""),
                "observacao": item.observacao or "",
                "veiculo_id": item.veiculo_id,
                "concluido": bool(item.concluido),
                "status_execucao": status_execucao,
                "servidores": servidores_por_item.get(item.id, []),
            }
        )
    return out


def salvar_programacao(unidade_id: int, data_ref: date, payload: dict[str, Any], user) -> dict[str, Any]:
    itens_in = payload.get("itens") or []
    metas_ids, servidores_ids_ativos, veiculos_ids = _ids_permitidos(unidade_id)

    with transaction.atomic():
        prog = (
            Programacao.objects.select_for_update()
            .filter(unidade_id=unidade_id, data=data_ref)
            .first()
        )
        if not prog:
            prog = Programacao.objects.create(
                unidade_id=unidade_id,
                data=data_ref,
                criado_por=user,
                observacao=payload.get("observacao") or "",
            )
        elif payload.get("observacao") is not None:
            Programacao.objects.filter(pk=prog.pk).update(observacao=payload.get("observacao") or "")

        existentes = {
            row.id: row
            for row in ProgramacaoItem.objects.filter(programacao_id=prog.id).select_for_update()
        }

        ids_payload: set[int] = set()
        total_links = 0

        for raw in itens_in:
            try:
                meta_id = int(raw.get("meta_id"))
            except (TypeError, ValueError):
                continue
            if meta_id not in metas_ids:
                continue

            try:
                veiculo_id = int(raw.get("veiculo_id")) if raw.get("veiculo_id") not in (None, "", "null") else None
            except (TypeError, ValueError):
                veiculo_id = None
            if veiculo_id is not None and veiculo_id not in veiculos_ids:
                veiculo_id = None

            srv: list[int] = []
            seen: set[int] = set()
            for sid in raw.get("servidores_ids") or []:
                try:
                    sid_int = int(sid)
                except (TypeError, ValueError):
                    continue
                if sid_int in seen or sid_int not in servidores_ids_ativos:
                    continue
                seen.add(sid_int)
                srv.append(sid_int)

            try:
                item_id = int(raw.get("id")) if raw.get("id") not in (None, "", "null") else None
            except (TypeError, ValueError):
                item_id = None

            item = existentes.get(item_id) if item_id else None
            if item:
                ProgramacaoItem.objects.filter(pk=item.id).update(
                    meta_id=meta_id,
                    observacao=(raw.get("observacao") or ""),
                    veiculo_id=veiculo_id,
                )
            else:
                item = ProgramacaoItem.objects.create(
                    programacao_id=prog.id,
                    meta_id=meta_id,
                    observacao=(raw.get("observacao") or ""),
                    veiculo_id=veiculo_id,
                    concluido=False,
                )

            ids_payload.add(item.id)
            ProgramacaoItemServidor.objects.filter(item_id=item.id).delete()
            if srv:
                ProgramacaoItemServidor.objects.bulk_create(
                    [ProgramacaoItemServidor(item_id=item.id, servidor_id=sid) for sid in srv]
                )
                total_links += len(srv)

        orfaos = [item_id for item_id in existentes.keys() if item_id not in ids_payload]
        if orfaos:
            ProgramacaoItemServidor.objects.filter(item_id__in=orfaos).delete()
            ProgramacaoItem.objects.filter(id__in=orfaos).delete()

    return {
        "ok": True,
        "programacao_id": prog.id,
        "itens": len(ids_payload),
        "servidores_vinculados": total_links,
    }


def concluir_item(
    unidade_id: int,
    item_id: int,
    user,
    *,
    realizada: bool,
    observacao: str = "",
    status_execucao: str | None = None,
) -> ProgramacaoItem:
    with transaction.atomic():
        item = (
            ProgramacaoItem.objects.select_for_update()
            .select_related("programacao")
            .get(pk=item_id, programacao__unidade_id=unidade_id)
        )
        status = (status_execucao or "").strip().lower()
        if status not in {EXECUTADA, NAO_REALIZADA, NAO_REALIZADA_JUSTIFICADA, PENDENTE}:
            status = EXECUTADA if realizada else PENDENTE

        if status == EXECUTADA:
            item.concluido = True
            item.concluido_em = timezone.now()
            item.nao_realizada_justificada = False
            item.concluido_por_id = getattr(user, "id", None)
        elif status in {NAO_REALIZADA, NAO_REALIZADA_JUSTIFICADA}:
            item.concluido = False
            item.concluido_em = timezone.now()
            item.nao_realizada_justificada = status == NAO_REALIZADA_JUSTIFICADA
            item.concluido_por_id = getattr(user, "id", None)
        else:
            item.concluido = False
            item.concluido_em = None
            item.nao_realizada_justificada = False
            item.concluido_por_id = None

        if observacao is not None:
            item.observacao = (observacao or "").strip()

        item.save(
            update_fields=[
                "concluido",
                "concluido_em",
                "nao_realizada_justificada",
                "concluido_por_id",
                "observacao",
            ]
        )
        return item


def listar_servidores_para_data(unidade_id: int, data_ref: date) -> list[dict[str, Any]]:
    # Mantido simples aqui para reutilizacao em endpoints; impedimentos detalhados
    # continuam no modulo de views legado.
    return list(
        Servidor.objects.filter(unidade_id=unidade_id, ativo=True)
        .order_by("nome")
        .values("id", "nome")
    )
