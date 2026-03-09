from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time
from typing import Any

from django.utils import timezone

from core.utils import get_unidade_atual_id
from programar.models import ProgramacaoItem
from programar.status import ITEM_STATUS_LABELS, PENDENTE

from relatorios.models import ProgramacaoHistorico
from .programacao_history_service import snapshot_programacao_dia


def _dt_start(value: date):
    return timezone.make_aware(datetime.combine(value, time.min))


def _dt_end(value: date):
    return timezone.make_aware(datetime.combine(value, time.max))


def _format_periodo(data_inicial: date, data_final: date) -> str:
    return f"{data_inicial.strftime('%d/%m/%Y')} -> {data_final.strftime('%d/%m/%Y')}"


def _status_label(status: str) -> str:
    return ITEM_STATUS_LABELS.get(status, ITEM_STATUS_LABELS[PENDENTE])


def _normalize_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    return dict(snapshot or {})


def _current_items_in_period(unidade_id: int, data_inicial: date, data_final: date):
    return list(
        ProgramacaoItem.objects.filter(
            programacao__unidade_id=unidade_id,
            programacao__data__gte=data_inicial,
            programacao__data__lte=data_final,
        )
        .select_related("programacao")
        .order_by("programacao__data", "id")
    )


def _history_items_map(unidade_id: int, data_inicial: date, data_final: date):
    start_dt = _dt_start(data_inicial)
    end_dt = _dt_end(data_final)
    qs = (
        ProgramacaoHistorico.objects.filter(
            unidade_id=unidade_id,
            data_programacao__gte=data_inicial,
            data_programacao__lte=data_final,
        )
        .order_by("item_id", "criado_em", "id")
    )
    by_item: dict[int, list[ProgramacaoHistorico]] = defaultdict(list)
    for entry in qs:
        if entry.item_id:
            by_item[int(entry.item_id)].append(entry)
    return by_item, start_dt, end_dt


def _snapshot_programacao_item(item: ProgramacaoItem) -> dict[str, Any]:
    return snapshot_programacao_dia(item.programacao.unidade_id, item.programacao.data)["items"].get(item.id, {})


def _resolve_state_at_end(
    *,
    current_snapshot: dict[str, Any] | None,
    historico: list[ProgramacaoHistorico],
    end_dt,
) -> tuple[str, dict[str, Any]]:
    current = _normalize_snapshot(current_snapshot)
    ate_fim = [entry for entry in historico if entry.criado_em <= end_dt]
    apos_fim = [entry for entry in historico if entry.criado_em > end_dt]

    if ate_fim:
        ultimo = ate_fim[-1]
        if ultimo.evento in {
            ProgramacaoHistorico.EVENTO_ATIVIDADE_REMOVIDA,
            ProgramacaoHistorico.EVENTO_PROGRAMACAO_EXCLUIDA,
        }:
            return "removida", _normalize_snapshot(ultimo.snapshot_antes)
        return ultimo.status_depois or (ultimo.snapshot_depois or {}).get("status_execucao", PENDENTE), _normalize_snapshot(ultimo.snapshot_depois)

    if apos_fim:
        primeiro = apos_fim[0]
        snap_antes = _normalize_snapshot(primeiro.snapshot_antes)
        if snap_antes:
            return snap_antes.get("status_execucao", PENDENTE), snap_antes
        if primeiro.evento == ProgramacaoHistorico.EVENTO_ATIVIDADE_CRIADA:
            return "nao_existia", {}

    if current:
        return current.get("status_execucao", PENDENTE), current

    return "removida", {}


def _build_history_section(unidade_id: int, data_inicial: date, data_final: date) -> dict[str, Any]:
    historico = list(
        ProgramacaoHistorico.objects.filter(
            unidade_id=unidade_id,
            data_programacao__gte=data_inicial,
            data_programacao__lte=data_final,
            criado_em__gte=_dt_start(data_inicial),
            criado_em__lte=_dt_end(data_final),
        )
        .select_related("usuario")
        .order_by("-criado_em", "-id")
    )
    return {
        "entries": historico,
        "total": len(historico),
    }


def _build_performance_section(unidade_id: int, data_inicial: date, data_final: date) -> dict[str, Any]:
    by_item, start_dt, end_dt = _history_items_map(unidade_id, data_inicial, data_final)
    current_items = _current_items_in_period(unidade_id, data_inicial, data_final)
    current_snapshots = {item.id: _snapshot_programacao_item(item) for item in current_items}

    baseline: dict[int, dict[str, Any]] = {}
    start_limit = start_dt.replace(hour=23, minute=59, second=59)
    for item in current_items:
        if getattr(item, "criado_em", None) and item.criado_em <= start_limit:
            baseline[item.id] = current_snapshots.get(item.id, {})

    for item_id, entries in by_item.items():
        created_hint = None
        for entry in entries:
            snap = entry.snapshot_antes or entry.snapshot_depois or {}
            raw_created = snap.get("criado_em") or ""
            if raw_created and created_hint is None:
                try:
                    created_hint = datetime.fromisoformat(raw_created)
                    if timezone.is_naive(created_hint):
                        created_hint = timezone.make_aware(created_hint)
                except Exception:
                    created_hint = None
        if created_hint and created_hint > start_limit:
            continue
        if item_id not in baseline:
            for entry in entries:
                snap = entry.snapshot_antes or entry.snapshot_depois or {}
                if snap:
                    baseline[item_id] = snap
                    break

    rows: list[dict[str, Any]] = []
    counters = {
        "executada": 0,
        "nao_realizada": 0,
        "nao_realizada_justificada": 0,
        "pendente": 0,
        "removida": 0,
    }

    for item_id, initial_snapshot in sorted(
        baseline.items(),
        key=lambda pair: (
            pair[1].get("programacao_data", ""),
            pair[1].get("meta_titulo", ""),
            pair[0],
        ),
    ):
        final_status, final_snapshot = _resolve_state_at_end(
            current_snapshot=current_snapshots.get(item_id),
            historico=by_item.get(item_id, []),
            end_dt=end_dt,
        )
        if final_status in counters:
            counters[final_status] += 1
        rows.append(
            {
                "item_id": item_id,
                "data_programacao": initial_snapshot.get("programacao_data", ""),
                "data_programacao_label": (
                    datetime.strptime(initial_snapshot.get("programacao_data", ""), "%Y-%m-%d").strftime("%d/%m/%Y")
                    if initial_snapshot.get("programacao_data")
                    else "-"
                ),
                "titulo": initial_snapshot.get("meta_titulo", "") or f"Item #{item_id}",
                "servidores": [srv.get("nome", "") for srv in initial_snapshot.get("servidores", [])],
                "veiculo": (
                    (final_snapshot or initial_snapshot).get("veiculo_nome")
                    or initial_snapshot.get("veiculo_nome")
                    or "-"
                ),
                "status_final": final_status,
                "status_final_label": "Removida" if final_status == "removida" else _status_label(final_status),
            }
        )

    return {
        "rows": rows,
        "counters": counters,
        "total": len(rows),
    }


def _build_indicators_section(
    unidade_id: int,
    data_inicial: date,
    data_final: date,
    desempenho: dict[str, Any],
) -> dict[str, Any]:
    history_qs = ProgramacaoHistorico.objects.filter(
        unidade_id=unidade_id,
        criado_em__gte=_dt_start(data_inicial),
        criado_em__lte=_dt_end(data_final),
    )
    added_ids = set(
        item_id for item_id in history_qs.filter(evento=ProgramacaoHistorico.EVENTO_ATIVIDADE_CRIADA).values_list("item_id", flat=True) if item_id
    )
    removed_ids = set(
        item_id for item_id in history_qs.filter(evento=ProgramacaoHistorico.EVENTO_ATIVIDADE_REMOVIDA).values_list("item_id", flat=True) if item_id
    )
    changed_ids = set(
        item_id
        for item_id in history_qs.exclude(
            evento__in=[
                ProgramacaoHistorico.EVENTO_ATIVIDADE_CRIADA,
                ProgramacaoHistorico.EVENTO_ATIVIDADE_REMOVIDA,
                ProgramacaoHistorico.EVENTO_PROGRAMACAO_EXCLUIDA,
            ]
        ).values_list("item_id", flat=True)
        if item_id
    )

    counters = desempenho.get("counters", {})
    total_programadas = desempenho.get("total", 0) + len(added_ids)

    return {
        "cards": [
            {"label": "Total de atividades programadas", "value": total_programadas},
            {"label": "Atividades concluidas", "value": counters.get("executada", 0)},
            {"label": "Atividades nao realizadas", "value": counters.get("nao_realizada", 0)},
            {"label": "Atividades nao realizadas justificadas", "value": counters.get("nao_realizada_justificada", 0)},
            {"label": "Atividades pendentes", "value": counters.get("pendente", 0)},
            {"label": "Atividades alteradas", "value": len(changed_ids)},
            {"label": "Atividades adicionadas", "value": len(added_ids)},
            {"label": "Atividades removidas", "value": len(removed_ids)},
        ]
    }


def build_programacao_report(*, request, data_inicial: date, data_final: date, include_sections: dict[str, bool]):
    unidade_id = get_unidade_atual_id(request)
    historico = _build_history_section(unidade_id, data_inicial, data_final) if include_sections.get("historico") else None
    desempenho = _build_performance_section(unidade_id, data_inicial, data_final) if include_sections.get("desempenho") or include_sections.get("indicadores") else {"rows": [], "counters": {}, "total": 0}
    indicadores = _build_indicators_section(unidade_id, data_inicial, data_final, desempenho) if include_sections.get("indicadores") else None

    return {
        "periodo_label": _format_periodo(data_inicial, data_final),
        "gerado_em": timezone.localtime(),
        "historico": historico,
        "desempenho": desempenho if include_sections.get("desempenho") else None,
        "indicadores": indicadores,
        "include_sections": include_sections,
    }
