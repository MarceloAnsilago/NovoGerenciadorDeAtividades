from __future__ import annotations

from datetime import date

EXECUTADA = "executada"
PENDENTE = "pendente"
CANCELADA = "cancelada"
NAO_REALIZADA = "nao_realizada"
NAO_REALIZADA_JUSTIFICADA = "nao_realizada_justificada"
REMARCADA_CONCLUIDA = "remarcada_concluida"

ITEM_STATUS_LABELS = {
    EXECUTADA: "Concluida",
    PENDENTE: "Pendente",
    CANCELADA: "Cancelada",
    NAO_REALIZADA: "Não realizada - mas continua em aberto",
    NAO_REALIZADA_JUSTIFICADA: "Nao realizada justificada",
    REMARCADA_CONCLUIDA: "Remarcada e concluida",
}


def remarcacao_origem_label(
    *,
    item_id: int | None,
    programacao_data: date | None,
    veiculo_nome: str = "",
    veiculo_placa: str = "",
) -> str:
    partes: list[str] = []
    if programacao_data:
        partes.append(programacao_data.strftime("%d/%m/%Y"))
    if item_id:
        partes.append(f"Item #{item_id}")

    veiculo_nome = str(veiculo_nome or "").strip()
    veiculo_placa = str(veiculo_placa or "").strip()
    if veiculo_nome and veiculo_placa:
        partes.append(f"{veiculo_nome} ({veiculo_placa})")
    elif veiculo_nome or veiculo_placa:
        partes.append(veiculo_nome or veiculo_placa)

    return " - ".join(partes) if partes else "Origem da substituicao"


def item_execucao_status_from_fields(
    concluido: bool,
    concluido_em,
    cancelada: bool = False,
    nao_realizada_justificada: bool = False,
    remarcado_de_id: int | None = None,
) -> str:
    if concluido:
        if remarcado_de_id:
            return REMARCADA_CONCLUIDA
        return EXECUTADA
    if cancelada:
        return CANCELADA
    if nao_realizada_justificada:
        return NAO_REALIZADA_JUSTIFICADA
    if concluido_em:
        return NAO_REALIZADA
    return PENDENTE


def item_execucao_label(status: str) -> str:
    return ITEM_STATUS_LABELS.get(status, ITEM_STATUS_LABELS[PENDENTE])


def item_permanece_aberto(
    concluido: bool,
    *,
    cancelada: bool = False,
    nao_realizada_justificada: bool = False,
    concluido_em=None,
) -> bool:
    return (not concluido) and (not cancelada) and (not nao_realizada_justificada) and (not concluido_em)


def is_auto_concluida_expediente(
    *,
    meta_id: int | None,
    meta_expediente_id: int | None,
    programacao_data: date | None,
    concluido: bool,
    concluido_em,
    cancelada: bool = False,
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

    if concluido or concluido_em or cancelada or nao_realizada_justificada:
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
    cancelada: bool = False,
    nao_realizada_justificada: bool = False,
    remarcado_de_id: int | None = None,
    today: date | None = None,
) -> str:
    status = item_execucao_status_from_fields(
        concluido,
        concluido_em,
        cancelada,
        nao_realizada_justificada,
        remarcado_de_id,
    )
    if is_auto_concluida_expediente(
        meta_id=meta_id,
        meta_expediente_id=meta_expediente_id,
        programacao_data=programacao_data,
        concluido=concluido,
        concluido_em=concluido_em,
        cancelada=cancelada,
        nao_realizada_justificada=nao_realizada_justificada,
        today=today,
    ):
        return EXECUTADA
    return status
