import unittest
import json
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from atividades.models import Area, Atividade
from core.models import No
from metas.models import Meta, MetaAlocacao, ProgressoMeta
from programar.models import Programacao, ProgramacaoItem, ProgramacaoItemServidor
from programar.status import (
    CANCELADA,
    EXECUTADA,
    NAO_REALIZADA,
    NAO_REALIZADA_JUSTIFICADA,
    PENDENTE,
    REMARCADA_CONCLUIDA,
    is_auto_concluida_expediente,
    item_execucao_label,
    item_execucao_status_from_fields,
    item_permanece_aberto,
)
from programar.views_legacy import _resolve_expediente_admin_report
from servidores.models import Servidor


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

    def test_resolve_status_for_cancelled_item(self):
        status = item_execucao_status_from_fields(
            concluido=False,
            concluido_em=object(),
            cancelada=True,
            nao_realizada_justificada=False,
        )
        self.assertEqual(status, CANCELADA)

    def test_justified_item_does_not_remain_open(self):
        self.assertFalse(item_permanece_aberto(concluido=False, nao_realizada_justificada=True))

    def test_regular_non_execution_keeps_item_open(self):
        self.assertTrue(item_permanece_aberto(concluido=False, nao_realizada_justificada=False))

    def test_cancelled_item_does_not_remain_open(self):
        self.assertFalse(item_permanece_aberto(concluido=False, cancelada=True, concluido_em=object()))

    def test_non_execution_label_indicates_item_remains_open(self):
        self.assertEqual(
            item_execucao_label(NAO_REALIZADA),
            "Não realizada - mas continua em aberto",
        )

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


class ExpedienteAdminReportTest(unittest.TestCase):
    def test_inclui_servidor_livre_ausente_no_expediente_salvo(self):
        self.assertEqual(
            _resolve_expediente_admin_report(
                ["Brenner", "Robson"],
                ["Brenner"],
                expediente_desativado=False,
            ),
            ["Brenner", "Robson"],
        )

    def test_nao_exibe_expediente_quando_desativado_explicitamente(self):
        self.assertEqual(
            _resolve_expediente_admin_report(
                ["Brenner", "Robson"],
                ["Brenner"],
                expediente_desativado=True,
            ),
            [],
        )


@override_settings(META_EXPEDIENTE_ID=888909)
class SalvarProgramacaoExpedienteTest(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="tester_save_programar", password="123456")
        self.unidade = No.objects.create(nome="ULSAV Save", tipo="setor")
        self.area = Area.objects.create(code="AREA_SAVE", nome="Area Save")
        self.atividade = Atividade.objects.create(
            titulo="Atividade campo",
            descricao="",
            area=self.area,
            unidade_origem=self.unidade,
            criado_por=self.user,
        )
        self.meta_campo = Meta.objects.create(
            unidade_criadora=self.unidade,
            atividade=self.atividade,
            titulo="Meta campo",
            descricao="",
            quantidade_alvo=1,
            criado_por=self.user,
        )
        self.meta_expediente = Meta.objects.create(
            id=888909,
            unidade_criadora=self.unidade,
            atividade=None,
            titulo="Expediente administrativo",
            descricao="",
            quantidade_alvo=0,
            criado_por=self.user,
        )
        self.servidor = Servidor.objects.create(unidade=self.unidade, nome="Servidor Teste")
        self.client.force_login(self.user)
        session = self.client.session
        session["contexto_atual"] = self.unidade.id
        session.save()

    def _post_salvar(self, expediente_manual_ids=None):
        payload = {
            "data": "2026-06-12",
            "observacao": "",
            "incluir_expediente": True,
            "itens": [
                {
                    "meta_id": self.meta_campo.id,
                    "observacao": "",
                    "veiculo_id": None,
                    "servidores_ids": [self.servidor.id],
                },
                {
                    "meta_id": self.meta_expediente.id,
                    "observacao": "",
                    "veiculo_id": None,
                    "servidores_ids": [self.servidor.id],
                    "expediente_manual_servidores_ids": expediente_manual_ids or [],
                },
            ],
        }
        return self.client.post(
            reverse("programar:salvar_programacao"),
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_remove_do_expediente_servidor_ja_alocado_em_campo(self):
        response = self._post_salvar()

        self.assertEqual(response.status_code, 200)
        item_expediente = ProgramacaoItem.objects.get(meta_id=self.meta_expediente.id)
        self.assertFalse(
            ProgramacaoItemServidor.objects.filter(
                item=item_expediente,
                servidor=self.servidor,
            ).exists()
        )

    def test_preserva_no_expediente_quando_duplicidade_foi_manual(self):
        response = self._post_salvar(expediente_manual_ids=[self.servidor.id])

        self.assertEqual(response.status_code, 200)
        item_expediente = ProgramacaoItem.objects.get(meta_id=self.meta_expediente.id)
        self.assertTrue(
            ProgramacaoItemServidor.objects.filter(
                item=item_expediente,
                servidor=self.servidor,
            ).exists()
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

    def _criar_item(self, *, data_ref, concluido=False, concluido_em=None, cancelada=False, nao_realizada_justificada=False):
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
            cancelada=cancelada,
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

    def test_exibe_status_cancelada_no_formulario(self):
        item = self._criar_item(data_ref=timezone.localdate())

        response = self.client.get(reverse("programar:concluir-item-form", args=[item.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="cancelada"')

    def test_rejeita_status_cancelada_sem_justificativa(self):
        item = self._criar_item(data_ref=timezone.localdate())

        response = self.client.post(
            reverse("programar:concluir-item-form", args=[item.id]),
            {"status_execucao": CANCELADA, "observacoes": ""},
        )

        item.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(item.cancelada)
        self.assertContains(response, "Informe uma observa")

    def test_salva_status_cancelada_com_justificativa(self):
        item = self._criar_item(data_ref=timezone.localdate())

        response = self.client.post(
            reverse("programar:concluir-item-form", args=[item.id]),
            {"status_execucao": CANCELADA, "observacoes": "Atividade cancelada pela chefia."},
            follow=False,
        )

        item.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertFalse(item.concluido)
        self.assertTrue(item.cancelada)

    def test_redireciona_para_programar_com_data_se_next_for_informado(self):
        item = self._criar_item(data_ref=date(2026, 3, 15))
        next_url = f"{reverse('programar:calendario')}?selected_date=2026-03-15&open_modal=1"

        response = self.client.post(
            reverse("programar:concluir-item-form", args=[item.id]),
            {
                "source": "minhas-metas",
                "status_execucao": EXECUTADA,
                "observacoes": "",
                "next": next_url,
            },
            follow=False,
        )

        item.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(item.concluido)
        self.assertEqual(response["Location"], next_url)

    def test_nao_exibe_confirmacao_ao_abrir_formulario_com_meta_concluida(self):
        item = self._criar_item(data_ref=date(2026, 5, 5))
        alocacao = MetaAlocacao.objects.create(
            meta=self.meta,
            unidade=self.unidade,
            quantidade_alocada=2,
            atribuida_por=self.user,
        )
        ProgressoMeta.objects.create(
            alocacao=alocacao,
            quantidade=2,
            registrado_por=self.user,
        )
        next_url = f"{reverse('programar:calendario')}?selected_date=2026-05-05&open_modal=1"

        response = self.client.get(
            reverse("programar:concluir-item-form", args=[item.id]),
            {"source": "minhas-metas", "next": next_url},
        )

        item.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(item.concluido)
        self.assertNotContains(response, "Esta meta já foi concluída. Deseja encerrar a meta?")

    def test_exibe_confirmacao_apos_salvar_conclusao_quando_meta_esta_concluida(self):
        self._criar_item(
            data_ref=date(2026, 5, 4),
            concluido=True,
            concluido_em=timezone.now(),
        )
        item = self._criar_item(data_ref=date(2026, 5, 5))
        alocacao = MetaAlocacao.objects.create(
            meta=self.meta,
            unidade=self.unidade,
            quantidade_alocada=2,
            atribuida_por=self.user,
        )
        ProgressoMeta.objects.create(
            alocacao=alocacao,
            quantidade=2,
            registrado_por=self.user,
        )
        next_url = f"{reverse('programar:calendario')}?selected_date=2026-05-05&open_modal=1"

        response = self.client.post(
            reverse("programar:concluir-item-form", args=[item.id]),
            {
                "source": "minhas-metas",
                "next": next_url,
                "status_execucao": EXECUTADA,
                "observacoes": "",
            },
        )

        item.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(item.concluido)
        self.assertContains(response, "Esta meta já foi concluída. Deseja encerrar a meta?")
        self.assertContains(response, "selected_date=2026-05-05")
        self.assertContains(response, "open_modal=1")
        self.assertContains(response, reverse("metas:encerrar-meta", args=[self.meta.id]))

    def test_exibe_confirmacao_apos_salvar_nao_realizada_justificada_quando_meta_esta_concluida(self):
        self._criar_item(
            data_ref=date(2026, 5, 4),
            concluido=True,
            concluido_em=timezone.now(),
        )
        item = self._criar_item(data_ref=date(2026, 5, 5))
        alocacao = MetaAlocacao.objects.create(
            meta=self.meta,
            unidade=self.unidade,
            quantidade_alocada=2,
            atribuida_por=self.user,
        )
        ProgressoMeta.objects.create(
            alocacao=alocacao,
            quantidade=2,
            registrado_por=self.user,
        )
        next_url = f"{reverse('programar:calendario')}?selected_date=2026-05-05&open_modal=1"

        response = self.client.post(
            reverse("programar:concluir-item-form", args=[item.id]),
            {
                "source": "minhas-metas",
                "next": next_url,
                "status_execucao": NAO_REALIZADA_JUSTIFICADA,
                "observacoes": "Justificada pela chefia.",
            },
        )

        item.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(item.concluido)
        self.assertTrue(item.nao_realizada_justificada)
        self.assertContains(response, "Esta meta já foi concluída. Deseja encerrar a meta?")

    def test_nao_exibe_confirmacao_quando_meta_ainda_tem_item_solucionado_faltando(self):
        self.meta.quantidade_alvo = 5
        self.meta.save(update_fields=["quantidade_alvo"])
        MetaAlocacao.objects.create(
            meta=self.meta,
            unidade=self.unidade,
            quantidade_alocada=5,
            atribuida_por=self.user,
        )
        for day in (3, 4, 5):
            self._criar_item(
                data_ref=date(2026, 5, day),
                concluido=True,
                concluido_em=timezone.now(),
            )
        item = self._criar_item(data_ref=date(2026, 5, 6))
        next_url = f"{reverse('programar:calendario')}?selected_date=2026-05-06&open_modal=1"

        response = self.client.post(
            reverse("programar:concluir-item-form", args=[item.id]),
            {
                "source": "minhas-metas",
                "next": next_url,
                "status_execucao": EXECUTADA,
                "observacoes": "",
            },
        )

        item.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(item.concluido)

    def test_encerrar_meta_retorna_para_next_original_do_fluxo_minhas_metas(self):
        item = self._criar_item(data_ref=date(2026, 5, 5))
        alocacao = MetaAlocacao.objects.create(
            meta=self.meta,
            unidade=self.unidade,
            quantidade_alocada=2,
            atribuida_por=self.user,
        )
        ProgressoMeta.objects.create(
            alocacao=alocacao,
            quantidade=2,
            registrado_por=self.user,
        )
        next_url = f"{reverse('programar:calendario')}?selected_date=2026-05-05&open_modal=1"

        response = self.client.post(
            reverse("metas:encerrar-meta", args=[self.meta.id]),
            {
                "next": "/metas/atividades/",
                "source": "minhas-metas",
                "flow_next": next_url,
                "encerrar_agora": "1",
                "confirmar_pendentes": "1",
            },
            follow=False,
        )

        self.meta.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], next_url)
        self.assertTrue(self.meta.encerrada)
        self.assertFalse(item.concluido)


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
