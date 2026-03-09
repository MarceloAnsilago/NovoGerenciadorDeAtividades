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
