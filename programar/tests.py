import unittest
from datetime import date, timedelta

from programar.status import (
    EXECUTADA,
    NAO_REALIZADA,
    NAO_REALIZADA_JUSTIFICADA,
    PENDENTE,
    is_auto_concluida_expediente,
    item_execucao_status_from_fields,
    item_permanece_aberto,
)


class ItemStatusTest(unittest.TestCase):
    def test_resolve_status_prioritizes_justified_non_execution(self):
        status = item_execucao_status_from_fields(
            concluido=False,
            concluido_em=object(),
            nao_realizada_justificada=True,
        )
        self.assertEqual(status, NAO_REALIZADA_JUSTIFICADA)

    def test_resolve_status_for_regular_non_execution(self):
        status = item_execucao_status_from_fields(
            concluido=False,
            concluido_em=object(),
            nao_realizada_justificada=False,
        )
        self.assertEqual(status, NAO_REALIZADA)

    def test_resolve_status_for_completed_item(self):
        status = item_execucao_status_from_fields(
            concluido=True,
            concluido_em=object(),
            nao_realizada_justificada=False,
        )
        self.assertEqual(status, EXECUTADA)

    def test_resolve_status_for_pending_item(self):
        status = item_execucao_status_from_fields(
            concluido=False,
            concluido_em=None,
            nao_realizada_justificada=False,
        )
        self.assertEqual(status, PENDENTE)

    def test_justified_item_does_not_remain_open(self):
        self.assertFalse(item_permanece_aberto(concluido=False, nao_realizada_justificada=True))

    def test_regular_non_execution_keeps_item_open(self):
        self.assertTrue(item_permanece_aberto(concluido=False, nao_realizada_justificada=False))

    def test_auto_conclui_expediente_when_past_and_pending(self):
        today = date(2026, 3, 9)
        self.assertTrue(
            is_auto_concluida_expediente(
                meta_id=999909,
                meta_expediente_id=999909,
                programacao_data=today - timedelta(days=1),
                concluido=False,
                concluido_em=None,
                nao_realizada_justificada=False,
                today=today,
            )
        )

    def test_does_not_auto_conclui_expediente_for_future(self):
        today = date(2026, 3, 9)
        self.assertTrue(
            is_auto_concluida_expediente(
                meta_id=999909,
                meta_expediente_id=999909,
                programacao_data=today,
                concluido=False,
                concluido_em=None,
                nao_realizada_justificada=False,
                today=today,
            )
        )
        self.assertFalse(
            is_auto_concluida_expediente(
                meta_id=999909,
                meta_expediente_id=999909,
                programacao_data=today + timedelta(days=1),
                concluido=False,
                concluido_em=None,
                nao_realizada_justificada=False,
                today=today,
            )
        )

    def test_does_not_auto_conclui_expediente_if_already_closed_or_not_pending(self):
        today = date(2026, 3, 9)
        past = today - timedelta(days=3)
        self.assertFalse(
            is_auto_concluida_expediente(
                meta_id=999909,
                meta_expediente_id=999909,
                programacao_data=past,
                concluido=True,
                concluido_em=None,
                nao_realizada_justificada=False,
                today=today,
            )
        )
        self.assertFalse(
            is_auto_concluida_expediente(
                meta_id=999909,
                meta_expediente_id=999909,
                programacao_data=past,
                concluido=False,
                concluido_em=object(),
                nao_realizada_justificada=False,
                today=today,
            )
        )
        self.assertFalse(
            is_auto_concluida_expediente(
                meta_id=999909,
                meta_expediente_id=999909,
                programacao_data=past,
                concluido=False,
                concluido_em=None,
                nao_realizada_justificada=True,
                today=today,
            )
        )
