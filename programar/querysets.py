from django.db.models import Q


def item_conta_como_programado_q() -> Q:
    return Q(cancelada=False) & (
        Q(concluido=True)
        | Q(concluido_em__isnull=True)
        | Q(nao_realizada_justificada=True)
    )
