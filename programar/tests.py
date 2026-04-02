import unittest
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from atividades.models import Area, Atividade
from core.models import No
from metas.models import Meta, MetaAlocacao, ProgressoMeta
from programar.models import Programacao, ProgramacaoItem
from programar.status import (
    EXECUTADA,
    NAO_REALIZADA,
    NAO_REALIZADA_JUSTIFICADA,
    PENDENTE,
    REMARCADA_CONCLUIDA,
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

    def test_resolve_status_for_rescheduled_completed_item(self):
        status = item_execucao_status_from_fields(
            concluido=True,
            concluido_em=object(),
            nao_realizada_justificada=False,
            remarcado_de_id=10,
        )
        self.assertEqual(status, REMARCADA_CONCLUIDA)

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


class ConcluirItemFormTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="tester_programar", password="123456")
        self.unidade = No.objects.create(nome="ULSAV Teste", tipo="setor")
        self.area = Area.objects.create(code="AREA_PROG", nome="Area Programar")
        self.atividade = Atividade.objects.create(
            titulo="Atividade de teste",
            descricao="",
            area=self.area,
            unidade_origem=self.unidade,
            criado_por=self.user,
        )
        self.meta = Meta.objects.create(
            unidade_criadora=self.unidade,
            atividade=self.atividade,
            titulo="Meta teste",
            descricao="meta",
            quantidade_alvo=2,
            criado_por=self.user,
        )
        self.client.force_login(self.user)
        session = self.client.session
        session["contexto_atual"] = self.unidade.id
        session.save()

    def _criar_item(self, *, data_ref, concluido=False, concluido_em=None, nao_realizada_justificada=False):
        programacao = Programacao.objects.create(
            data=data_ref,
            unidade=self.unidade,
            criado_por=self.user,
        )
        return ProgramacaoItem.objects.create(
            programacao=programacao,
            meta=self.meta,
            concluido=concluido,
            concluido_em=concluido_em,
            nao_realizada_justificada=nao_realizada_justificada,
        )

    def test_oculta_status_remarcado_sem_item_nao_realizado_anterior(self):
        item = self._criar_item(data_ref=timezone.localdate())

        response = self.client.get(reverse("programar:concluir-item-form", args=[item.id]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'value="remarcada_concluida"')

    def test_exibe_status_remarcado_quando_ha_item_nao_realizado_anterior(self):
        item_origem = self._criar_item(
            data_ref=timezone.localdate() - timedelta(days=1),
            concluido=False,
            concluido_em=timezone.now(),
            nao_realizada_justificada=False,
        )
        item = self._criar_item(data_ref=timezone.localdate())

        response = self.client.get(reverse("programar:concluir-item-form", args=[item.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="remarcada_concluida"')
        self.assertContains(response, "Atividade substituída na meta")
        self.assertNotContains(response, f'value="{item_origem.id}" selected')

    def test_rejeita_status_remarcado_sem_item_nao_realizado_anterior(self):
        item = self._criar_item(data_ref=timezone.localdate())

        response = self.client.post(
            reverse("programar:concluir-item-form", args=[item.id]),
            {"status_execucao": REMARCADA_CONCLUIDA, "observacoes": ""},
        )

        item.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(item.remarcado_de_id, None)
        self.assertFalse(item.concluido)
        self.assertContains(response, "O status Remarcada e concluída só pode ser usado")

    def test_exibe_status_remarcado_quando_revisao_vem_de_nao_realizadas(self):
        item = self._criar_item(
            data_ref=timezone.localdate(),
            concluido=False,
            concluido_em=timezone.now(),
            nao_realizada_justificada=False,
        )

        response = self.client.get(
            reverse("programar:concluir-item-form", args=[item.id]),
            {"source": "minhas-metas"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="remarcada_concluida"')
        self.assertContains(response, f'value="{item.id}" selected')

    def test_permita_salvar_remarcada_quando_revisao_vem_de_nao_realizadas(self):
        item = self._criar_item(
            data_ref=timezone.localdate(),
            concluido=False,
            concluido_em=timezone.now(),
            nao_realizada_justificada=False,
        )

        response = self.client.post(
            reverse("programar:concluir-item-form", args=[item.id]),
            {
                "source": "minhas-metas",
                "status_execucao": REMARCADA_CONCLUIDA,
                "remarcado_de_id": str(item.id),
                "observacoes": "Revisto em nao realizadas",
            },
            follow=False,
        )

        item.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(item.concluido)
        self.assertEqual(item.remarcado_de_id, item.id)


class MetasDisponiveisApiTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="tester_programar_api", password="123456")
        self.unidade = No.objects.create(nome="ULSAV API", tipo="setor")
        self.area = Area.objects.create(code="AREA_API", nome="Area API")
        self.atividade = Atividade.objects.create(
            titulo="Atividade API",
            descricao="",
            area=self.area,
            unidade_origem=self.unidade,
            criado_por=self.user,
        )
        self.meta = Meta.objects.create(
            unidade_criadora=self.unidade,
            atividade=self.atividade,
            titulo="Meta API",
            descricao="meta api",
            quantidade_alvo=5,
            criado_por=self.user,
            data_limite=timezone.localdate() + timedelta(days=10),
        )
        self.client.force_login(self.user)
        session = self.client.session
        session["contexto_atual"] = self.unidade.id
        session.save()

    def test_metas_disponiveis_agrega_alocacoes_e_progresso_sem_perder_dados(self):
        raiz = MetaAlocacao.objects.create(
            meta=self.meta,
            unidade=self.unidade,
            quantidade_alocada=2,
            atribuida_por=self.user,
        )
        filha = MetaAlocacao.objects.create(
            meta=self.meta,
            unidade=self.unidade,
            quantidade_alocada=3,
            parent=raiz,
            atribuida_por=self.user,
        )
        ProgressoMeta.objects.create(
            alocacao=raiz,
            quantidade=1,
            registrado_por=self.user,
        )
        ProgressoMeta.objects.create(
            alocacao=filha,
            quantidade=2,
            registrado_por=self.user,
        )

        response = self.client.get(
            reverse("programar:metas_disponiveis"),
            {"data": timezone.localdate().isoformat()},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["metas"]), 1)
        meta_payload = payload["metas"][0]
        self.assertEqual(meta_payload["id"], self.meta.id)
        self.assertEqual(meta_payload["alocado_unidade"], 5)
        self.assertEqual(meta_payload["executado_unidade"], 3)
