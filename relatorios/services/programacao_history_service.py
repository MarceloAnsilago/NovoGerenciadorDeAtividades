from __future__ import annotations

from datetime import date
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from programar.models import Programacao, ProgramacaoItem, ProgramacaoItemServidor
from programar.status import EXECUTADA, is_auto_concluida_expediente, item_execucao_label, item_execucao_status_from_fields

from relatorios.models import ProgramacaoHistorico


def _snapshot_empty(data_ref: date) -> dict[str, Any]:
    return {
        "programacao_id": None,
        "data": data_ref.isoformat(),
        "observacao": "",
        "items": {},
    }


def snapshot_programacao_dia(unidade_id: int | None, data_ref: date) -> dict[str, Any]:
    if not unidade_id:
        return _snapshot_empty(data_ref)

    prog = Programacao.objects.filter(unidade_id=unidade_id, data=data_ref).first()
    if not prog:
        return _snapshot_empty(data_ref)

    itens = list(
        ProgramacaoItem.objects.filter(programacao_id=prog.id)
        .select_related("meta", "meta__atividade", "veiculo")
        .order_by("id")
    )
    item_ids = [item.id for item in itens]
    servidores_por_item: dict[int, list[dict[str, Any]]] = {item_id: [] for item_id in item_ids}
    if item_ids:
        links = (
            ProgramacaoItemServidor.objects.filter(item_id__in=item_ids)
            .select_related("servidor")
            .order_by("item_id", "servidor__nome", "servidor_id")
        )
        for link in links:
            servidores_por_item.setdefault(link.item_id, []).append(
                {"id": link.servidor_id, "nome": getattr(link.servidor, "nome", "")}
            )

    items_map: dict[int, dict[str, Any]] = {}
    meta_expediente_id = getattr(settings, "META_EXPEDIENTE_ID", None)
    try:
        meta_expediente_id = int(meta_expediente_id) if meta_expediente_id is not None else None
    except (TypeError, ValueError):
        meta_expediente_id = None
    today = timezone.localdate()
    for item in itens:
        meta = getattr(item, "meta", None)
        atividade = getattr(meta, "atividade", None) if meta else None
        titulo = (
            getattr(meta, "display_titulo", None)
            or getattr(meta, "titulo", None)
            or getattr(atividade, "titulo", None)
            or ""
        )
        concluido_db = bool(getattr(item, "concluido", False))
        concluido_em = getattr(item, "concluido_em", None)
        nao_realizada_justificada = bool(getattr(item, "nao_realizada_justificada", False))
        auto_concluida_expediente = is_auto_concluida_expediente(
            meta_id=item.meta_id,
            meta_expediente_id=meta_expediente_id,
            programacao_data=data_ref,
            concluido=concluido_db,
            concluido_em=concluido_em,
            nao_realizada_justificada=nao_realizada_justificada,
            today=today,
        )
        status_execucao = EXECUTADA if auto_concluida_expediente else item_execucao_status_from_fields(
            concluido_db,
            concluido_em,
            nao_realizada_justificada,
        )
        servidores = servidores_por_item.get(item.id, [])
        items_map[item.id] = {
            "id": item.id,
            "programacao_id": prog.id,
            "programacao_data": data_ref.isoformat(),
            "criado_em": item.criado_em.isoformat() if getattr(item, "criado_em", None) else "",
            "meta_id": item.meta_id,
            "meta_titulo": str(titulo or "").strip(),
            "observacao": item.observacao or "",
            "veiculo_id": item.veiculo_id,
            "veiculo_nome": getattr(getattr(item, "veiculo", None), "nome", "") or "",
            "status_execucao": status_execucao,
            "servidores": servidores,
            "servidores_ids": [srv["id"] for srv in servidores],
        }

    return {
        "programacao_id": prog.id,
        "data": data_ref.isoformat(),
        "observacao": getattr(prog, "observacao", "") or "",
        "items": items_map,
    }


def _build_history_entry(
    *,
    unidade_id: int,
    data_ref: date,
    user,
    origem: str,
    evento: str,
    descricao: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    detalhes: dict[str, Any] | None = None,
) -> ProgramacaoHistorico:
    snap_before = before or {}
    snap_after = after or {}
    ref = snap_after or snap_before
    return ProgramacaoHistorico(
        unidade_id=unidade_id,
        usuario=getattr(user, "id", None) and user or None,
        meta_id=ref.get("meta_id"),
        data_programacao=data_ref,
        programacao_id=ref.get("programacao_id"),
        item_id=ref.get("id"),
        evento=evento,
        origem=origem or "",
        titulo_item=ref.get("meta_titulo", "") or "",
        descricao=descricao,
        status_antes=snap_before.get("status_execucao", "") or "",
        status_depois=snap_after.get("status_execucao", "") or "",
        detalhes=detalhes or {},
        snapshot_antes=snap_before,
        snapshot_depois=snap_after,
    )


def record_programacao_day_diff(
    *,
    unidade_id: int | None,
    data_ref: date,
    user,
    before_snapshot: dict[str, Any] | None,
    after_snapshot: dict[str, Any] | None,
    origem: str = "modal",
) -> None:
    if not unidade_id:
        return

    before_items = (before_snapshot or {}).get("items", {}) or {}
    after_items = (after_snapshot or {}).get("items", {}) or {}
    before_ids = set(before_items.keys())
    after_ids = set(after_items.keys())
    historico: list[ProgramacaoHistorico] = []

    for item_id in sorted(after_ids - before_ids):
        after = after_items[item_id]
        historico.append(
            _build_history_entry(
                unidade_id=unidade_id,
                data_ref=data_ref,
                user=user,
                origem=origem,
                evento=ProgramacaoHistorico.EVENTO_ATIVIDADE_CRIADA,
                descricao=f"Atividade '{after.get('meta_titulo') or item_id}' criada na programacao.",
                after=after,
            )
        )

    for item_id in sorted(before_ids - after_ids):
        before = before_items[item_id]
        historico.append(
            _build_history_entry(
                unidade_id=unidade_id,
                data_ref=data_ref,
                user=user,
                origem=origem,
                evento=ProgramacaoHistorico.EVENTO_ATIVIDADE_REMOVIDA,
                descricao=f"Atividade '{before.get('meta_titulo') or item_id}' removida da programacao.",
                before=before,
            )
        )

    for item_id in sorted(before_ids & after_ids):
        before = before_items[item_id]
        after = after_items[item_id]

        if before.get("meta_id") != after.get("meta_id"):
            historico.append(
                _build_history_entry(
                    unidade_id=unidade_id,
                    data_ref=data_ref,
                    user=user,
                    origem=origem,
                    evento=ProgramacaoHistorico.EVENTO_META_ALTERADA,
                    descricao=(
                        f"Meta alterada de '{before.get('meta_titulo') or '-'}' "
                        f"para '{after.get('meta_titulo') or '-'}'."
                    ),
                    before=before,
                    after=after,
                    detalhes={
                        "meta_antes": before.get("meta_titulo", ""),
                        "meta_depois": after.get("meta_titulo", ""),
                    },
                )
            )

        if (before.get("observacao") or "") != (after.get("observacao") or ""):
            historico.append(
                _build_history_entry(
                    unidade_id=unidade_id,
                    data_ref=data_ref,
                    user=user,
                    origem=origem,
                    evento=ProgramacaoHistorico.EVENTO_OBSERVACAO_ALTERADA,
                    descricao=f"Observacao da atividade '{after.get('meta_titulo') or item_id}' alterada.",
                    before=before,
                    after=after,
                    detalhes={
                        "observacao_antes": before.get("observacao", ""),
                        "observacao_depois": after.get("observacao", ""),
                    },
                )
            )

        if before.get("veiculo_id") != after.get("veiculo_id"):
            historico.append(
                _build_history_entry(
                    unidade_id=unidade_id,
                    data_ref=data_ref,
                    user=user,
                    origem=origem,
                    evento=ProgramacaoHistorico.EVENTO_VEICULO_ALTERADO,
                    descricao=(
                        f"Veiculo da atividade '{after.get('meta_titulo') or item_id}' alterado "
                        f"de '{before.get('veiculo_nome') or 'Nenhum'}' para '{after.get('veiculo_nome') or 'Nenhum'}'."
                    ),
                    before=before,
                    after=after,
                    detalhes={
                        "veiculo_antes": before.get("veiculo_nome", ""),
                        "veiculo_depois": after.get("veiculo_nome", ""),
                    },
                )
            )

        if before.get("status_execucao") != after.get("status_execucao"):
            historico.append(
                _build_history_entry(
                    unidade_id=unidade_id,
                    data_ref=data_ref,
                    user=user,
                    origem=origem,
                    evento=ProgramacaoHistorico.EVENTO_STATUS_ALTERADO,
                    descricao=(
                        f"Status da atividade '{after.get('meta_titulo') or item_id}' alterado "
                        f"de '{item_execucao_label(before.get('status_execucao', ''))}' "
                        f"para '{item_execucao_label(after.get('status_execucao', ''))}'."
                    ),
                    before=before,
                    after=after,
                )
            )

        before_srv = {srv["id"]: srv for srv in before.get("servidores", [])}
        after_srv = {srv["id"]: srv for srv in after.get("servidores", [])}

        for srv_id in sorted(set(after_srv.keys()) - set(before_srv.keys())):
            srv = after_srv[srv_id]
            historico.append(
                _build_history_entry(
                    unidade_id=unidade_id,
                    data_ref=data_ref,
                    user=user,
                    origem=origem,
                    evento=ProgramacaoHistorico.EVENTO_SERVIDOR_ADICIONADO,
                    descricao=(
                        f"Servidor '{srv.get('nome') or srv_id}' adicionado "
                        f"na atividade '{after.get('meta_titulo') or item_id}'."
                    ),
                    before=before,
                    after=after,
                    detalhes={"servidor_id": srv_id, "servidor_nome": srv.get("nome", "")},
                )
            )

        for srv_id in sorted(set(before_srv.keys()) - set(after_srv.keys())):
            srv = before_srv[srv_id]
            historico.append(
                _build_history_entry(
                    unidade_id=unidade_id,
                    data_ref=data_ref,
                    user=user,
                    origem=origem,
                    evento=ProgramacaoHistorico.EVENTO_SERVIDOR_REMOVIDO,
                    descricao=(
                        f"Servidor '{srv.get('nome') or srv_id}' removido "
                        f"da atividade '{before.get('meta_titulo') or item_id}'."
                    ),
                    before=before,
                    after=after,
                    detalhes={"servidor_id": srv_id, "servidor_nome": srv.get("nome", "")},
                )
            )

    before_prog_id = (before_snapshot or {}).get("programacao_id")
    after_prog_id = (after_snapshot or {}).get("programacao_id")
    if before_prog_id and not after_prog_id and before_items:
        historico.append(
            _build_history_entry(
                unidade_id=unidade_id,
                data_ref=data_ref,
                user=user,
                origem=origem,
                evento=ProgramacaoHistorico.EVENTO_PROGRAMACAO_EXCLUIDA,
                descricao="Programacao do dia excluida.",
                detalhes={"total_itens_removidos": len(before_items)},
            )
        )

    if historico:
        ProgramacaoHistorico.objects.bulk_create(historico)


def record_programacao_day_diff_after_commit(
    *,
    unidade_id: int | None,
    data_ref: date,
    user,
    before_snapshot: dict[str, Any] | None,
    after_snapshot: dict[str, Any] | None,
    origem: str = "modal",
) -> None:
    transaction.on_commit(
        lambda: record_programacao_day_diff(
            unidade_id=unidade_id,
            data_ref=data_ref,
            user=user,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            origem=origem,
        )
    )
