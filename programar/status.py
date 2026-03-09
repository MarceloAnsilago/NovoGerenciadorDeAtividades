from __future__ import annotations

from datetime import date

EXECUTADA = "executada"
PENDENTE = "pendente"
NAO_REALIZADA = "nao_realizada"
NAO_REALIZADA_JUSTIFICADA = "nao_realizada_justificada"

ITEM_STATUS_LABELS = {
    EXECUTADA: "Concluida",
    PENDENTE: "Pendente",
    NAO_REALIZADA: "Nao realizada",
    NAO_REALIZADA_JUSTIFICADA: "Nao realizada justificada",
}


def item_execucao_status_from_fields(
    concluido: bool,
    concluido_em,
    nao_realizada_justificada: bool = False,
) -> str:
    if concluido:
        return EXECUTADA
    if nao_realizada_justificada:
        return NAO_REALIZADA_JUSTIFICADA
    if concluido_em:
        return NAO_REALIZADA
    return PENDENTE


def item_execucao_label(status: str) -> str:
    return ITEM_STATUS_LABELS.get(status, ITEM_STATUS_LABELS[PENDENTE])


def item_permanece_aberto(concluido: bool, nao_realizada_justificada: bool = False) -> bool:
    return (not concluido) and (not nao_realizada_justificada)


def is_auto_concluida_expediente(
    *,
    meta_id: int | None,
    meta_expediente_id: int | None,
    programacao_data: date | None,
    concluido: bool,
    concluido_em,
    nao_realizada_justificada: bool = False,
    today: date | None = None,
) -> bool:
    """
    Regras de negócio:
    - "Expediente administrativo" (meta padrão) não é encerrado pelo usuário.
    - Se estiver pendente e a data da programação já chegou (ou passou), considera como concluído.
    """
    if not meta_expediente_id or meta_id is None:
        return False
    try:
        if int(meta_id) != int(meta_expediente_id):
            return False
    except Exception:
        return False

    if concluido or concluido_em or nao_realizada_justificada:
        return False

    if not programacao_data:
        return False

    ref_today = today or date.today()
    return programacao_data <= ref_today


def item_execucao_status_with_expediente_rule(
    *,
    meta_id: int | None,
    meta_expediente_id: int | None,
    programacao_data: date | None,
    concluido: bool,
    concluido_em,
    nao_realizada_justificada: bool = False,
    today: date | None = None,
) -> str:
    status = item_execucao_status_from_fields(concluido, concluido_em, nao_realizada_justificada)
    if is_auto_concluida_expediente(
        meta_id=meta_id,
        meta_expediente_id=meta_expediente_id,
        programacao_data=programacao_data,
        concluido=concluido,
        concluido_em=concluido_em,
        nao_realizada_justificada=nao_realizada_justificada,
        today=today,
    ):
        return EXECUTADA
    return status
