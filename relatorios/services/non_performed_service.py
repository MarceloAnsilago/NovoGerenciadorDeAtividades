from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from django.conf import settings

from programar.models import ProgramacaoItem, ProgramacaoItemServidor


def _secondary_activity_name(meta) -> str | None:
    atividade = getattr(meta, "atividade", None)
    atividade_nome = getattr(atividade, "titulo", None) or getattr(atividade, "nome", None)
    atividade_nome = str(atividade_nome or "").strip()
    if not atividade_nome:
        return None

    titulo_principal = getattr(meta, "display_titulo", None) or getattr(meta, "titulo", None)
    titulo_principal = str(titulo_principal or "").strip()
    if titulo_principal and titulo_principal == atividade_nome:
        return None
    return atividade_nome


def build_non_performed_groups(*, unidade_id: int, data_inicial: date, data_final: date) -> list[dict[str, Any]]:
    itens_qs = (
        ProgramacaoItem.objects
        .select_related("programacao", "meta", "meta__atividade", "veiculo")
        .filter(
            programacao__unidade_id=unidade_id,
            programacao__data__gte=data_inicial,
            programacao__data__lte=data_final,
            concluido=False,
            concluido_em__isnull=False,
            cancelada=False,
            nao_realizada_justificada=False,
        )
        .order_by("meta__titulo", "meta_id", "-programacao__data", "-id")
    )

    meta_expediente_id = getattr(settings, "META_EXPEDIENTE_ID", None)
    try:
        meta_expediente_id = int(meta_expediente_id) if meta_expediente_id is not None else None
    except (TypeError, ValueError):
        meta_expediente_id = None
    if meta_expediente_id is not None:
        itens_qs = itens_qs.exclude(meta_id=meta_expediente_id)

    itens = list(itens_qs)
    if not itens:
        return []

    item_ids = [item.id for item in itens]
    servidores_por_item: dict[int, list[str]] = defaultdict(list)
    for link in (
        ProgramacaoItemServidor.objects
        .select_related("servidor")
        .filter(item_id__in=item_ids)
        .order_by("item_id", "servidor__nome", "servidor_id")
    ):
        nome = getattr(getattr(link, "servidor", None), "nome", "") or f"Servidor {link.servidor_id}"
        servidores_por_item[link.item_id].append(nome)

    grupos: dict[tuple[str, str, int], dict[str, Any]] = {}
    for item in itens:
        meta = getattr(item, "meta", None)
        programacao = getattr(item, "programacao", None)
        if not meta or not programacao:
            continue

        meta_id = int(getattr(meta, "id", 0) or 0)
        meta_titulo = getattr(meta, "display_titulo", None) or getattr(meta, "titulo", None) or "(sem titulo)"
        meta_titulo = str(meta_titulo).strip() or "(sem titulo)"
        atividade_nome = _secondary_activity_name(meta) or ""
        group_key = (meta_titulo.casefold(), atividade_nome.casefold(), meta_id)

        grupo = grupos.get(group_key)
        if grupo is None:
            grupo = {
                "meta_id": meta_id or None,
                "meta_titulo": meta_titulo,
                "atividade_nome": atividade_nome or None,
                "rows": [],
                "total": 0,
            }
            grupos[group_key] = grupo

        veiculo = getattr(item, "veiculo", None)
        veiculo_nome = str(getattr(veiculo, "nome", "") or "").strip()
        veiculo_placa = str(getattr(veiculo, "placa", "") or "").strip()
        if veiculo_nome and veiculo_placa:
            veiculo_label = f"{veiculo_nome} ({veiculo_placa})"
        else:
            veiculo_label = veiculo_nome or veiculo_placa or ""

        grupo["rows"].append(
            {
                "item_id": item.id,
                "data": getattr(programacao, "data", None),
                "servidores": servidores_por_item.get(item.id, []),
                "veiculo": veiculo_label,
                "observacao": str(getattr(item, "observacao", "") or "").strip(),
                "concluido_em": getattr(item, "concluido_em", None),
            }
        )
        grupo["total"] += 1

    return list(grupos.values())
