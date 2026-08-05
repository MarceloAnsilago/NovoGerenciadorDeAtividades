from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time
from typing import Any

from django.conf import settings
from django.utils import timezone

from core.utils import get_unidade_atual_id
from programar.models import ProgramacaoItem
from programar.status import (
    CANCELADA,
    ENCERRADA_AUTOMATICAMENTE,
    ENCERRADA_AUTOMATICAMENTE_MARKER,
    EXECUTADA,
    ITEM_STATUS_LABELS,
    NAO_REALIZADA,
    NAO_REALIZADA_JUSTIFICADA,
    PENDENTE,
    REMARCADA_CONCLUIDA,
    item_execucao_status_from_fields,
)

from relatorios.models import ProgramacaoHistorico
from .programacao_history_service import snapshot_programacao_dia
from .non_performed_service import build_non_performed_groups
from veiculos.models import Veiculo


def _dt_start(value: date):
    return timezone.make_aware(datetime.combine(value, time.min))


def _dt_end(value: date):
    return timezone.make_aware(datetime.combine(value, time.max))


def _format_periodo(data_inicial: date, data_final: date) -> str:
    return f"{data_inicial.strftime('%d/%m/%Y')} a {data_final.strftime('%d/%m/%Y')}"


def _status_label(status: str) -> str:
    return ITEM_STATUS_LABELS.get(status, ITEM_STATUS_LABELS[PENDENTE])


def _normalize_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    return dict(snapshot or {})

def _snapshot_veiculo_label(snapshot: dict[str, Any] | None) -> str:
    snap = snapshot or {}
    raw = str(snap.get("veiculo_label") or "").strip()
    if raw:
        return raw
    nome = str(snap.get("veiculo_nome") or "").strip()
    placa = str(snap.get("veiculo_placa") or "").strip()
    if nome and placa:
        return f"{nome} ({placa})"
    return nome or placa


def _history_entry_observacao(entry: ProgramacaoHistorico) -> str:
    detalhes = entry.detalhes or {}
    for key in ("observacao_depois", "observacao"):
        value = str(detalhes.get(key) or "").strip()
        if value:
            return value

    for snapshot in (entry.snapshot_depois, entry.snapshot_antes):
        value = str((snapshot or {}).get("observacao") or "").strip()
        if value:
            return value

    return ""


def _meta_expediente_id() -> int | None:
    raw_id = getattr(settings, "META_EXPEDIENTE_ID", None)
    try:
        return int(raw_id) if raw_id is not None else None
    except (TypeError, ValueError):
        return None


def _filter_history_entries(historico: list[ProgramacaoHistorico]) -> list[ProgramacaoHistorico]:
    meta_expediente_id = _meta_expediente_id()
    if meta_expediente_id is None:
        return historico

    changed_item_ids = {
        int(entry.item_id)
        for entry in historico
        if entry.item_id and entry.evento != ProgramacaoHistorico.EVENTO_ATIVIDADE_CRIADA
    }

    return [
        entry
        for entry in historico
        if not (
            entry.evento == ProgramacaoHistorico.EVENTO_ATIVIDADE_CRIADA
            and entry.meta_id == meta_expediente_id
            and (not entry.item_id or int(entry.item_id) not in changed_item_ids)
        )
    ]


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


def _current_programacao_indicator_counts(unidade_id: int, data_inicial: date, data_final: date) -> dict[str, Any]:
    qs = (
        ProgramacaoItem.objects.filter(
            programacao__unidade_id=unidade_id,
            programacao__data__gte=data_inicial,
            programacao__data__lte=data_final,
        )
        .exclude(meta_id__isnull=True)
        .select_related("programacao")
        .order_by("programacao__data", "id")
    )
    meta_expediente_id = _meta_expediente_id()
    if meta_expediente_id is not None:
        qs = qs.exclude(meta_id=meta_expediente_id)

    counters = {
        EXECUTADA: 0,
        REMARCADA_CONCLUIDA: 0,
        CANCELADA: 0,
        NAO_REALIZADA: 0,
        NAO_REALIZADA_JUSTIFICADA: 0,
        ENCERRADA_AUTOMATICAMENTE: 0,
        PENDENTE: 0,
        "atrasada": 0,
    }
    today = timezone.localdate()
    total = 0
    for item in qs:
        total += 1
        status = item_execucao_status_from_fields(
            bool(getattr(item, "concluido", False)),
            getattr(item, "concluido_em", None),
            bool(getattr(item, "cancelada", False)),
            bool(getattr(item, "nao_realizada_justificada", False)),
            getattr(item, "remarcado_de_id", None),
            getattr(item, "observacao", "") or "",
        )
        if status in counters:
            counters[status] += 1
        programacao_data = getattr(getattr(item, "programacao", None), "data", None)
        if status == PENDENTE and programacao_data and programacao_data < today:
            counters["atrasada"] += 1

    return {"total": total, "counters": counters}


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


def _resolve_latest_state(
    *,
    current_snapshot: dict[str, Any] | None,
    historico: list[ProgramacaoHistorico],
) -> tuple[str, dict[str, Any]]:
    current = _normalize_snapshot(current_snapshot)
    if current:
        return current.get("status_execucao", PENDENTE), current

    if historico:
        ultimo = historico[-1]
        if ultimo.evento in {
            ProgramacaoHistorico.EVENTO_ATIVIDADE_REMOVIDA,
            ProgramacaoHistorico.EVENTO_PROGRAMACAO_EXCLUIDA,
        }:
            return "removida", _normalize_snapshot(ultimo.snapshot_antes)
        return ultimo.status_depois or (ultimo.snapshot_depois or {}).get("status_execucao", PENDENTE), _normalize_snapshot(ultimo.snapshot_depois)

    return "removida", {}


def _is_overdue_snapshot(status: str, snapshot: dict[str, Any], today: date) -> bool:
    if status != PENDENTE:
        return False
    if ENCERRADA_AUTOMATICAMENTE_MARKER in str(snapshot.get("observacao") or ""):
        return False

    raw_date = str(snapshot.get("programacao_data") or "").strip()
    if not raw_date:
        return False
    try:
        programacao_data = date.fromisoformat(raw_date)
    except ValueError:
        return False
    return programacao_data < today


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
    historico = _filter_history_entries(historico)
    for entry in historico:
        entry.observacao_evento = _history_entry_observacao(entry)
    return {
        "entries": historico,
        "total": len(historico),
    }


def _build_performance_section(unidade_id: int, data_inicial: date, data_final: date) -> dict[str, Any]:
    by_item, start_dt, end_dt = _history_items_map(unidade_id, data_inicial, data_final)
    current_items = _current_items_in_period(unidade_id, data_inicial, data_final)
    meta_expediente_id = _meta_expediente_id()
    if meta_expediente_id is not None:
        current_items = [item for item in current_items if int(getattr(item, "meta_id", 0) or 0) != meta_expediente_id]
    # Evita N chamadas repetidas por item (snapshot_programacao_dia consulta o dia inteiro).
    current_snapshots: dict[int, dict[str, Any]] = {}
    snapshots_by_day: dict[date, dict[int, dict[str, Any]]] = {}
    for item in current_items:
        data_ref = getattr(getattr(item, "programacao", None), "data", None)
        if not data_ref:
            current_snapshots[item.id] = {}
            continue
        if data_ref not in snapshots_by_day:
            snapshots_by_day[data_ref] = snapshot_programacao_dia(unidade_id, data_ref).get("items", {}) or {}
        current_snapshots[item.id] = snapshots_by_day[data_ref].get(item.id, {})
    today = timezone.localdate()

    baseline: dict[int, dict[str, Any]] = {}
    # Considera todo o período (inclusive atividades adicionadas após o 1º dia).
    end_limit = end_dt
    for item in current_items:
        if getattr(item, "criado_em", None) and item.criado_em > end_limit:
            # Item criado após o período não deve aparecer no desempenho do período.
            continue
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
        if created_hint and created_hint > end_limit:
            continue
        if item_id not in baseline:
            for entry in entries:
                snap = entry.snapshot_antes or entry.snapshot_depois or {}
                if meta_expediente_id is not None and int(snap.get("meta_id") or 0) == meta_expediente_id:
                    continue
                if snap:
                    baseline[item_id] = snap
                    break

    rows: list[dict[str, Any]] = []
    counters = {
        "executada": 0,
        "remarcada_concluida": 0,
        CANCELADA: 0,
        "nao_realizada": 0,
        "nao_realizada_justificada": 0,
        ENCERRADA_AUTOMATICAMENTE: 0,
        "pendente": 0,
        "atrasada": 0,
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
        final_status, final_snapshot = _resolve_latest_state(
            current_snapshot=current_snapshots.get(item_id),
            historico=by_item.get(item_id, []),
        )

        if meta_expediente_id is not None and int(initial_snapshot.get("meta_id") or 0) == meta_expediente_id:
            # Expediente administrativo deve ser "pendente" em datas futuras e "concluída" em datas atuais/passadas.
            # Mesmo se o item foi removido por efeitos colaterais de salvar (ex.: limpar servidores), não exibe como removida.
            if final_status == "removida":
                raw_date = str(initial_snapshot.get("programacao_data") or "").strip()
                try:
                    prog_day = date.fromisoformat(raw_date) if raw_date else None
                except ValueError:
                    prog_day = None
                final_status = EXECUTADA if (prog_day and prog_day <= today) else PENDENTE

        if final_status in counters:
            counters[final_status] += 1
        if _is_overdue_snapshot(final_status, final_snapshot or initial_snapshot, today):
            counters["atrasada"] += 1
        # Resolve veículo: preferir label do snapshot; fallback via ORM (nome + placa).
        veiculo_label = _snapshot_veiculo_label(final_snapshot) or _snapshot_veiculo_label(initial_snapshot)
        if not veiculo_label:
            veiculo_id = (final_snapshot or initial_snapshot).get("veiculo_id") or initial_snapshot.get("veiculo_id")
            try:
                veiculo_id_int = int(veiculo_id) if veiculo_id not in (None, "", "null") else None
            except (TypeError, ValueError):
                veiculo_id_int = None
            if veiculo_id_int:
                v = Veiculo.objects.filter(id=veiculo_id_int).values("nome", "placa").first()
                if v:
                    nome = str(v.get("nome") or "").strip()
                    placa = str(v.get("placa") or "").strip()
                    if nome and placa:
                        veiculo_label = f"{nome} ({placa})"
                    else:
                        veiculo_label = nome or placa

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
                "veiculo": veiculo_label or "-",
                "status_final": final_status,
                "status_final_label": "Removida" if final_status == "removida" else _status_label(final_status),
                "remarcado_de_label": final_snapshot.get("remarcado_de_label", "") or initial_snapshot.get("remarcado_de_label", ""),
            }
        )

    resumo_by_titulo: dict[str, dict[str, Any]] = {}
    for row in rows:
        titulo = str(row.get("titulo") or "").strip() or "-"
        status_final = str(row.get("status_final") or "").strip()
        if titulo not in resumo_by_titulo:
            resumo_by_titulo[titulo] = {"titulo": titulo, "total": 0, "total_base": 0, **{key: 0 for key in counters.keys()}}
        resumo_by_titulo[titulo]["total_base"] += 1
        if status_final != "removida":
            resumo_by_titulo[titulo]["total"] += 1
        if status_final == "removida":
            resumo_by_titulo[titulo]["removida"] += 1
        elif status_final in counters:
            resumo_by_titulo[titulo][status_final] += 1

    resumo_por_atividade = list(resumo_by_titulo.values())

    for row in resumo_por_atividade:
        total_periodo = int(row.get("total_base") or 0)
        total_atual_com_canceladas = int(row.get("total") or 0)
        executada = int(row.get("executada") or 0)
        remarcada_concluida = int(row.get("remarcada_concluida") or 0)
        cancelada = int(row.get(CANCELADA) or 0)
        removida = int(row.get("removida") or 0)
        encerrada_automaticamente = int(row.get(ENCERRADA_AUTOMATICAMENTE) or 0)
        total_atual = max(total_atual_com_canceladas - cancelada, 0)
        total_execucao = max(total_atual - encerrada_automaticamente, 0)
        row["total_periodo"] = total_periodo
        row["total_atual"] = total_atual
        row["total_execucao"] = total_execucao
        if total_execucao:
            row["execucao_percent"] = int(round(((executada + remarcada_concluida) * 100.0 / total_execucao), 0))
            row["execucao_percent_label"] = f"{row['execucao_percent']}%"
        else:
            row["execucao_percent"] = None
            row["execucao_percent_label"] = "-"
        row["cancelada_ou_removida"] = cancelada + removida

    resumo_por_atividade.sort(
        key=lambda r: (
            int(r.get("execucao_percent") if r.get("execucao_percent") is not None else -1),
            str(r.get("titulo") or "").casefold(),
            -int(r.get("total_atual") or 0),
        )
    )
    nao_realizadas_grupos = build_non_performed_groups(
        unidade_id=unidade_id,
        data_inicial=data_inicial,
        data_final=data_final,
    )

    return {
        "rows": rows,
        "counters": counters,
        "total": len(rows),
        "resumo_por_atividade": resumo_por_atividade,
        "nao_realizadas_grupos": nao_realizadas_grupos,
    }


def _build_indicators_section(
    unidade_id: int,
    data_inicial: date,
    data_final: date,
    desempenho: dict[str, Any],
) -> dict[str, Any]:
    history_qs = ProgramacaoHistorico.objects.filter(
        unidade_id=unidade_id,
        data_programacao__gte=data_inicial,
        data_programacao__lte=data_final,
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

    current_indicators = _current_programacao_indicator_counts(unidade_id, data_inicial, data_final)
    counters = current_indicators.get("counters", {})
    total_programadas = int(current_indicators.get("total", 0) or 0)
    total_desempenho = desempenho.get("total", 0)
    total_adicionadas_historico = len(added_ids)
    total_removidas_desempenho = int((desempenho.get("counters", {}) or {}).get("removida", 0) or 0)
    total_canceladas_atuais = int(counters.get(CANCELADA, 0) or 0)
    total_canceladas_removidas = total_canceladas_atuais + total_removidas_desempenho

    return {
        "cards": [
            {
                "label": "Total de atividades programadas",
                "value": total_programadas,
                "breakdown": [
                    {"label": "Atual: salvas no calendario", "value": total_programadas},
                    {
                        "label": f"Desempenho: {total_programadas} atuais + {total_removidas_desempenho} removidas",
                        "value": total_desempenho,
                    },
                    {"label": "Historico: adicionadas no periodo", "value": total_adicionadas_historico},
                ],
                "formula": f"Total = {total_programadas} - removidas so detalham o desempenho",
            },
            {
                "label": "Atividades concluidas",
                "value": counters.get(EXECUTADA, 0) + counters.get(REMARCADA_CONCLUIDA, 0),
            },
            {
                "label": "Atividades canceladas/removidas",
                "value": total_canceladas_removidas,
                "breakdown": [
                    {"label": "Canceladas atuais", "value": total_canceladas_atuais},
                    {"label": "Removidas no desempenho", "value": total_removidas_desempenho},
                ],
                "formula": f"Total = {total_canceladas_atuais} + {total_removidas_desempenho}",
            },
            {"label": "Atividades remarcadas e concluidas", "value": counters.get(REMARCADA_CONCLUIDA, 0)},
            {"label": "Atividades nao realizadas", "value": counters.get(NAO_REALIZADA, 0)},
            {"label": "Atividades nao realizadas justificadas", "value": counters.get(NAO_REALIZADA_JUSTIFICADA, 0)},
            {"label": "Atividades encerradas automaticamente", "value": counters.get(ENCERRADA_AUTOMATICAMENTE, 0)},
            {"label": "Atividades pendentes", "value": counters.get(PENDENTE, 0)},
            {"label": "Atividades atrasadas", "value": counters.get("atrasada", 0)},
            {"label": "Atividades alteradas", "value": len(changed_ids)},
            {"label": "Atividades adicionadas", "value": len(added_ids)},
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
