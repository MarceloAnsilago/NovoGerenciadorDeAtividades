from datetime import date, datetime, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from atividades.models import Area, Atividade
from core.models import No
from metas.models import Meta
from programar.models import Programacao, ProgramacaoItem
from programar.status import CANCELADA, ENCERRADA_AUTOMATICAMENTE_MARKER, EXECUTADA, PENDENTE
from relatorios.models import ProgramacaoHistorico


class RelatorioProgramacaoTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="tester_relatorio", password="123456")
        self.unidade = No.objects.create(nome="ULSAV Relatorio", tipo="setor")
        self.area = Area.objects.create(code="AREA_REL", nome="Area Relatorio")
        self.atividade = Atividade.objects.create(
            titulo="Fiscalizacao de viveiros",
            descricao="",
            area=self.area,
            unidade_origem=self.unidade,
            criado_por=self.user,
        )
        self.meta = Meta.objects.create(
            unidade_criadora=self.unidade,
            atividade=self.atividade,
            titulo="Titulo temporario",
            descricao="meta de teste",
            quantidade_alvo=2,
            criado_por=self.user,
        )

        self.programacao_1 = Programacao.objects.create(
            data=date(2026, 3, 10),
            unidade=self.unidade,
            criado_por=self.user,
        )
        self.programacao_2 = Programacao.objects.create(
            data=date(2026, 3, 11),
            unidade=self.unidade,
            criado_por=self.user,
        )
        ProgramacaoItem.objects.create(
            programacao=self.programacao_1,
            meta=self.meta,
            concluido=False,
            concluido_em=timezone.now(),
            nao_realizada_justificada=False,
            observacao="Primeira nao realizada",
        )
        ProgramacaoItem.objects.create(
            programacao=self.programacao_2,
            meta=self.meta,
            concluido=False,
            concluido_em=timezone.now(),
            nao_realizada_justificada=False,
            observacao="Segunda nao realizada",
        )

        self.client.force_login(self.user)
        session = self.client.session
        session["contexto_atual"] = self.unidade.id
        session.save()

    def test_relatorio_agrupar_nao_realizadas_por_meta_sem_duplicar_atividade(self):
        response = self.client.get(
            reverse("relatorios:programacao"),
            {
                "data_inicial": "2026-03-01",
                "data_final": "2026-03-31",
                "sec_desempenho": "1",
                "sec_historico": "1",
                "sec_indicadores": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        report = response.context["report"]
        grupos = report["desempenho"]["nao_realizadas_grupos"]

        self.assertEqual(len(grupos), 1)
        self.assertEqual(grupos[0]["meta_titulo"], "Fiscalizacao de viveiros")
        self.assertIsNone(grupos[0]["atividade_nome"])
        self.assertEqual(grupos[0]["total"], 2)
        self.assertEqual(len(grupos[0]["rows"]), 2)
        self.assertContains(response, "Atividades n")
        self.assertContains(response, "Primeira nao realizada")
        self.assertContains(response, "Segunda nao realizada")
        self.assertNotContains(response, "Atividade: Fiscalizacao de viveiros")

    def test_relatorio_destaca_remarcada_e_concluida(self):
        item_original = ProgramacaoItem.objects.create(
            programacao=self.programacao_1,
            meta=self.meta,
            concluido=False,
            concluido_em=timezone.now(),
            nao_realizada_justificada=False,
            observacao="Original nao realizada",
        )
        programacao_3 = Programacao.objects.create(
            data=date(2026, 3, 12),
            unidade=self.unidade,
            criado_por=self.user,
        )
        ProgramacaoItem.objects.create(
            programacao=programacao_3,
            meta=self.meta,
            concluido=True,
            concluido_em=timezone.now(),
            remarcado_de=item_original,
            observacao="Remarcada e concluida",
        )

        response = self.client.get(
            reverse("relatorios:programacao"),
            {
                "data_inicial": "2026-03-01",
                "data_final": "2026-03-31",
                "sec_desempenho": "1",
                "sec_indicadores": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        report = response.context["report"]
        resumo = {row["titulo"]: row for row in report["desempenho"]["resumo_por_atividade"]}
        self.assertEqual(resumo["Fiscalizacao de viveiros"]["remarcada_concluida"], 1)
        self.assertContains(response, "Remarcada e concluida")
        self.assertContains(response, "Atividades remarcadas e concluidas")
        self.assertContains(response, "Remarc.")
        self.assertContains(response, "Remov.")
        self.assertContains(response, f"Substituiu: 10/03/2026 - Item #{item_original.id}")

    def test_relatorio_considera_status_final_mesmo_quando_conclusao_ocorre_apos_periodo(self):
        item = ProgramacaoItem.objects.create(
            programacao=self.programacao_2,
            meta=self.meta,
            concluido=True,
            concluido_em=timezone.make_aware(datetime(2026, 4, 1, 9, 30)),
            nao_realizada_justificada=False,
            observacao="Concluida apos fechamento do mes",
        )

        snapshot_antes = {
            "id": item.id,
            "programacao_id": self.programacao_2.id,
            "programacao_data": "2026-03-11",
            "meta_id": self.meta.id,
            "meta_titulo": "Fiscalizacao de viveiros",
            "status_execucao": PENDENTE,
            "servidores": [],
        }
        snapshot_depois = {
            **snapshot_antes,
            "status_execucao": EXECUTADA,
        }
        historico = ProgramacaoHistorico.objects.create(
            unidade=self.unidade,
            usuario=self.user,
            meta=self.meta,
            data_programacao=self.programacao_2.data,
            programacao_id=self.programacao_2.id,
            item_id=item.id,
            evento=ProgramacaoHistorico.EVENTO_STATUS_ALTERADO,
            origem="teste",
            titulo_item="Fiscalizacao de viveiros",
            descricao="Status alterado depois do periodo filtrado.",
            status_antes=PENDENTE,
            status_depois=EXECUTADA,
            snapshot_antes=snapshot_antes,
            snapshot_depois=snapshot_depois,
        )
        ProgramacaoHistorico.objects.filter(pk=historico.pk).update(
            criado_em=timezone.make_aware(datetime(2026, 4, 1, 9, 31))
        )

        response = self.client.get(
            reverse("relatorios:programacao"),
            {
                "data_inicial": "2026-03-01",
                "data_final": "2026-03-31",
                "sec_desempenho": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        report = response.context["report"]
        row = next(report_row for report_row in report["desempenho"]["rows"] if report_row["item_id"] == item.id)
        self.assertEqual(row["status_final"], EXECUTADA)
        resumo = {report_row["titulo"]: report_row for report_row in report["desempenho"]["resumo_por_atividade"]}
        self.assertEqual(resumo["Fiscalizacao de viveiros"]["executada"], 1)

    def test_relatorio_prefere_estado_atual_quando_historico_do_item_ativo_esta_desatualizado(self):
        item = ProgramacaoItem.objects.create(
            programacao=self.programacao_2,
            meta=self.meta,
            concluido=True,
            concluido_em=timezone.make_aware(datetime(2026, 3, 31, 17, 19)),
            nao_realizada_justificada=False,
            observacao="Historico nao recebeu a mudanca de status",
        )

        ProgramacaoHistorico.objects.create(
            unidade=self.unidade,
            usuario=self.user,
            meta=self.meta,
            data_programacao=self.programacao_2.data,
            programacao_id=self.programacao_2.id,
            item_id=item.id,
            evento=ProgramacaoHistorico.EVENTO_ATIVIDADE_CRIADA,
            origem="teste",
            titulo_item="Fiscalizacao de viveiros",
            descricao="Item criado como pendente.",
            status_antes="",
            status_depois=PENDENTE,
            snapshot_antes={},
            snapshot_depois={
                "id": item.id,
                "programacao_id": self.programacao_2.id,
                "programacao_data": "2026-03-11",
                "meta_id": self.meta.id,
                "meta_titulo": "Fiscalizacao de viveiros",
                "status_execucao": PENDENTE,
                "servidores": [],
            },
        )

        response = self.client.get(
            reverse("relatorios:programacao"),
            {
                "data_inicial": "2026-03-01",
                "data_final": "2026-03-31",
                "sec_desempenho": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        report = response.context["report"]
        row = next(report_row for report_row in report["desempenho"]["rows"] if report_row["item_id"] == item.id)
        self.assertEqual(row["status_final"], EXECUTADA)

    def test_relatorio_exibe_cancelada_em_desempenho_e_resumo(self):
        item = ProgramacaoItem.objects.create(
            programacao=self.programacao_2,
            meta=self.meta,
            concluido=False,
            concluido_em=timezone.now(),
            cancelada=True,
            observacao="Agenda suspensa",
        )

        response = self.client.get(
            reverse("relatorios:programacao"),
            {
                "data_inicial": "2026-03-01",
                "data_final": "2026-03-31",
                "sec_desempenho": "1",
                "sec_indicadores": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        report = response.context["report"]
        row = next(report_row for report_row in report["desempenho"]["rows"] if report_row["item_id"] == item.id)
        self.assertEqual(row["status_final"], CANCELADA)
        resumo = {report_row["titulo"]: report_row for report_row in report["desempenho"]["resumo_por_atividade"]}
        self.assertEqual(resumo["Fiscalizacao de viveiros"]["cancelada"], 1)
        indicadores = {card["label"]: card["value"] for card in report["indicadores"]["cards"]}
        self.assertEqual(indicadores["Atividades canceladas/removidas"], 1)
        self.assertContains(response, "Cancelada")

    def test_relatorio_separa_canceladas_e_removidas_no_resumo(self):
        atividade = Atividade.objects.create(
            titulo="Fiscalizacao de laticinios",
            descricao="",
            area=self.area,
            unidade_origem=self.unidade,
            criado_por=self.user,
        )
        meta = Meta.objects.create(
            unidade_criadora=self.unidade,
            atividade=atividade,
            titulo="Laticinios",
            descricao="meta de teste",
            quantidade_alvo=2,
            criado_por=self.user,
        )
        ProgramacaoItem.objects.create(
            programacao=self.programacao_2,
            meta=meta,
            concluido=False,
            concluido_em=timezone.now(),
            cancelada=True,
            observacao="Cancelada no calendario",
        )
        snapshot_removida = {
            "id": 987654,
            "programacao_id": self.programacao_2.id,
            "programacao_data": "2026-03-11",
            "meta_id": meta.id,
            "meta_titulo": "Fiscalizacao de laticinios",
            "status_execucao": PENDENTE,
            "servidores": [],
        }
        ProgramacaoHistorico.objects.create(
            unidade=self.unidade,
            usuario=self.user,
            meta=meta,
            data_programacao=self.programacao_2.data,
            programacao_id=self.programacao_2.id,
            item_id=987654,
            evento=ProgramacaoHistorico.EVENTO_ATIVIDADE_REMOVIDA,
            origem="teste",
            titulo_item="Fiscalizacao de laticinios",
            descricao="Atividade removida da programacao.",
            status_antes=PENDENTE,
            status_depois="",
            snapshot_antes=snapshot_removida,
            snapshot_depois={},
        )

        response = self.client.get(
            reverse("relatorios:programacao"),
            {
                "data_inicial": "2026-03-01",
                "data_final": "2026-03-31",
                "sec_desempenho": "1",
                "sec_indicadores": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        resumo = {row["titulo"]: row for row in response.context["report"]["desempenho"]["resumo_por_atividade"]}
        row = resumo["Fiscalizacao de laticinios"]
        self.assertEqual(row["cancelada"], 1)
        self.assertEqual(row["removida"], 1)
        self.assertEqual(row["cancelada_ou_removida"], 2)
        self.assertEqual(row["total_atual"], 0)

    def test_relatorio_indicadores_de_historico_respeitam_data_programada_do_periodo(self):
        snapshot_removida = {
            "id": 876543,
            "programacao_id": 123456,
            "programacao_data": "2026-04-01",
            "meta_id": self.meta.id,
            "meta_titulo": "Fiscalizacao de viveiros",
            "status_execucao": PENDENTE,
            "servidores": [],
        }
        historico = ProgramacaoHistorico.objects.create(
            unidade=self.unidade,
            usuario=self.user,
            meta=self.meta,
            data_programacao=date(2026, 4, 1),
            programacao_id=123456,
            item_id=876543,
            evento=ProgramacaoHistorico.EVENTO_ATIVIDADE_REMOVIDA,
            origem="teste",
            titulo_item="Fiscalizacao de viveiros",
            descricao="Atividade de abril removida em marco.",
            status_antes=PENDENTE,
            status_depois="",
            snapshot_antes=snapshot_removida,
            snapshot_depois={},
        )
        ProgramacaoHistorico.objects.filter(pk=historico.pk).update(
            criado_em=timezone.make_aware(datetime(2026, 3, 20, 10, 0))
        )

        response = self.client.get(
            reverse("relatorios:programacao"),
            {
                "data_inicial": "2026-03-01",
                "data_final": "2026-03-31",
                "sec_desempenho": "0",
                "sec_historico": "0",
                "sec_indicadores": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        indicadores = {card["label"]: card["value"] for card in response.context["report"]["indicadores"]["cards"]}
        self.assertEqual(indicadores["Atividades canceladas/removidas"], 0)

    @override_settings(META_EXPEDIENTE_ID=777909)
    def test_relatorio_desempenho_nao_conta_expediente_administrativo(self):
        meta_expediente = Meta.objects.create(
            id=777909,
            unidade_criadora=self.unidade,
            atividade=None,
            titulo="Expediente administrativo",
            descricao="",
            quantidade_alvo=0,
            criado_por=self.user,
        )
        ProgramacaoItem.objects.create(
            programacao=self.programacao_2,
            meta=meta_expediente,
            concluido=False,
        )

        response = self.client.get(
            reverse("relatorios:programacao"),
            {
                "data_inicial": "2026-03-01",
                "data_final": "2026-03-31",
                "sec_desempenho": "1",
                "sec_indicadores": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        report = response.context["report"]
        self.assertEqual(report["desempenho"]["total"], 2)
        breakdown = {item["label"]: item["value"] for item in report["indicadores"]["cards"][0]["breakdown"]}
        self.assertEqual(breakdown["Atual: salvas no calendario"], 2)
        self.assertEqual(breakdown["Desempenho: 2 atuais + 0 removidas"], 2)

    def test_relatorio_indicadores_inclui_atrasadas_sem_encerradas_automaticamente(self):
        data_atrasada = timezone.localdate() - timedelta(days=1)
        programacao_atrasada = Programacao.objects.create(
            data=data_atrasada,
            unidade=self.unidade,
            criado_por=self.user,
        )
        ProgramacaoItem.objects.create(
            programacao=programacao_atrasada,
            meta=self.meta,
            concluido=False,
            concluido_em=None,
            nao_realizada_justificada=False,
            observacao="Pendente atrasada",
        )
        ProgramacaoItem.objects.create(
            programacao=programacao_atrasada,
            meta=self.meta,
            concluido=False,
            concluido_em=None,
            nao_realizada_justificada=False,
            observacao=f"Encerrado automaticamente ao encerrar a meta. {ENCERRADA_AUTOMATICAMENTE_MARKER}",
        )

        response = self.client.get(
            reverse("relatorios:programacao"),
            {
                "data_inicial": data_atrasada.replace(day=1).isoformat(),
                "data_final": data_atrasada.isoformat(),
                "sec_desempenho": "0",
                "sec_historico": "0",
                "sec_indicadores": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        indicadores = {card["label"]: card["value"] for card in response.context["report"]["indicadores"]["cards"]}
        self.assertEqual(indicadores["Atividades atrasadas"], 1)

    def test_relatorio_historico_exibe_observacao_do_evento(self):
        item = ProgramacaoItem.objects.create(
            programacao=self.programacao_2,
            meta=self.meta,
            concluido=True,
            concluido_em=timezone.now(),
            observacao="Equipe informou bloqueio no local",
        )
        snapshot_antes = {
            "id": item.id,
            "programacao_id": self.programacao_2.id,
            "programacao_data": "2026-03-11",
            "meta_id": self.meta.id,
            "meta_titulo": "Fiscalizacao de viveiros",
            "status_execucao": PENDENTE,
            "observacao": "",
            "servidores": [],
        }
        snapshot_depois = {
            **snapshot_antes,
            "status_execucao": EXECUTADA,
            "observacao": "Equipe informou bloqueio no local",
        }
        ProgramacaoHistorico.objects.create(
            unidade=self.unidade,
            usuario=self.user,
            meta=self.meta,
            data_programacao=self.programacao_2.data,
            programacao_id=self.programacao_2.id,
            item_id=item.id,
            evento=ProgramacaoHistorico.EVENTO_STATUS_ALTERADO,
            origem="status_form",
            titulo_item="Fiscalizacao de viveiros",
            descricao="Status alterado pela tela de conclusao.",
            status_antes=PENDENTE,
            status_depois=EXECUTADA,
            snapshot_antes=snapshot_antes,
            snapshot_depois=snapshot_depois,
        )

        response = self.client.get(
            reverse("relatorios:programacao"),
            {
                "data_inicial": "2026-03-01",
                "data_final": "2026-03-31",
                "sec_historico": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        entry = response.context["report"]["historico"]["entries"][0]
        self.assertEqual(entry.observacao_evento, "Equipe informou bloqueio no local")
        self.assertContains(response, "Observa")
        self.assertContains(response, "Equipe informou bloqueio no local")

    @override_settings(META_EXPEDIENTE_ID=777909)
    def test_relatorio_historico_oculta_criacao_expediente_sem_alteracao(self):
        meta_expediente = Meta.objects.create(
            id=777909,
            unidade_criadora=self.unidade,
            atividade=None,
            titulo="Expediente administrativo",
            descricao="",
            quantidade_alvo=0,
            criado_por=self.user,
        )
        item_campo = ProgramacaoItem.objects.create(
            programacao=self.programacao_2,
            meta=self.meta,
            concluido=False,
            observacao="Barreira voltou para pendente",
        )
        item_expediente = ProgramacaoItem.objects.create(
            programacao=self.programacao_2,
            meta=meta_expediente,
            concluido=False,
        )

        ProgramacaoHistorico.objects.create(
            unidade=self.unidade,
            usuario=self.user,
            meta=meta_expediente,
            data_programacao=self.programacao_2.data,
            programacao_id=self.programacao_2.id,
            item_id=item_expediente.id,
            evento=ProgramacaoHistorico.EVENTO_ATIVIDADE_CRIADA,
            origem="modal",
            titulo_item="Expediente administrativo",
            descricao="Atividade 'Expediente administrativo' criada na programacao.",
            status_antes="",
            status_depois=PENDENTE,
            snapshot_antes={},
            snapshot_depois={
                "id": item_expediente.id,
                "programacao_id": self.programacao_2.id,
                "programacao_data": "2026-03-11",
                "meta_id": meta_expediente.id,
                "meta_titulo": "Expediente administrativo",
                "status_execucao": PENDENTE,
                "servidores": [],
            },
        )
        ProgramacaoHistorico.objects.create(
            unidade=self.unidade,
            usuario=self.user,
            meta=self.meta,
            data_programacao=self.programacao_2.data,
            programacao_id=self.programacao_2.id,
            item_id=item_campo.id,
            evento=ProgramacaoHistorico.EVENTO_STATUS_ALTERADO,
            origem="status_form",
            titulo_item="Fiscalizacao de viveiros",
            descricao="Status da atividade 'Fiscalizacao de viveiros' alterado de 'Cancelada' para 'Pendente'.",
            status_antes=CANCELADA,
            status_depois=PENDENTE,
            snapshot_antes={
                "id": item_campo.id,
                "programacao_id": self.programacao_2.id,
                "programacao_data": "2026-03-11",
                "meta_id": self.meta.id,
                "meta_titulo": "Fiscalizacao de viveiros",
                "status_execucao": CANCELADA,
                "servidores": [],
            },
            snapshot_depois={
                "id": item_campo.id,
                "programacao_id": self.programacao_2.id,
                "programacao_data": "2026-03-11",
                "meta_id": self.meta.id,
                "meta_titulo": "Fiscalizacao de viveiros",
                "status_execucao": PENDENTE,
                "servidores": [],
            },
        )

        response = self.client.get(
            reverse("relatorios:programacao"),
            {
                "data_inicial": "2026-03-01",
                "data_final": "2026-03-31",
                "sec_historico": "1",
                "sec_desempenho": "0",
                "sec_indicadores": "0",
            },
        )

        self.assertEqual(response.status_code, 200)
        entries = response.context["report"]["historico"]["entries"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].item_id, item_campo.id)
        self.assertEqual(entries[0].evento, ProgramacaoHistorico.EVENTO_STATUS_ALTERADO)

    def test_encerrar_programacao_mes_bloqueia_item_pendente(self):
        programacao = Programacao.objects.create(
            data=date(2026, 4, 10),
            unidade=self.unidade,
            criado_por=self.user,
        )
        ProgramacaoItem.objects.create(
            programacao=programacao,
            meta=self.meta,
            concluido=False,
            concluido_em=None,
            cancelada=False,
            nao_realizada_justificada=False,
        )

        response = self.client.post(reverse("relatorios:programacao_encerrar_mes"), {"mes": "2026-04"})

        self.assertEqual(response.status_code, 409)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["pendentes"], 1)
        self.assertEqual(payload["nao_realizadas"], 0)
        self.assertIn("conclua os itens", payload["error"])
        programacao.refresh_from_db()
        self.assertFalse(programacao.concluida)

    def test_encerrar_programacao_mes_bloqueia_nao_realizada_em_aberto(self):
        programacao = Programacao.objects.create(
            data=date(2026, 5, 10),
            unidade=self.unidade,
            criado_por=self.user,
        )
        ProgramacaoItem.objects.create(
            programacao=programacao,
            meta=self.meta,
            concluido=False,
            concluido_em=timezone.now(),
            cancelada=False,
            nao_realizada_justificada=False,
        )

        response = self.client.post(reverse("relatorios:programacao_encerrar_mes"), {"mes": "2026-05"})

        self.assertEqual(response.status_code, 409)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["pendentes"], 0)
        self.assertEqual(payload["nao_realizadas"], 1)
        programacao.refresh_from_db()
        self.assertFalse(programacao.concluida)

    def test_encerrar_programacao_mes_permite_somente_itens_resolvidos(self):
        programacao = Programacao.objects.create(
            data=date(2026, 6, 10),
            unidade=self.unidade,
            criado_por=self.user,
        )
        ProgramacaoItem.objects.create(
            programacao=programacao,
            meta=self.meta,
            concluido=True,
            concluido_em=timezone.now(),
        )
        ProgramacaoItem.objects.create(
            programacao=programacao,
            meta=self.meta,
            concluido=False,
            concluido_em=timezone.now(),
            nao_realizada_justificada=True,
        )
        ProgramacaoItem.objects.create(
            programacao=programacao,
            meta=self.meta,
            concluido=False,
            cancelada=True,
        )

        response = self.client.post(reverse("relatorios:programacao_encerrar_mes"), {"mes": "2026-06"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        programacao.refresh_from_db()
        self.assertTrue(programacao.concluida)

    def test_encerrar_programacao_mes_ignora_origem_remarcada_e_concluida(self):
        programacao_original = Programacao.objects.create(
            data=date(2026, 8, 10),
            unidade=self.unidade,
            criado_por=self.user,
        )
        item_original = ProgramacaoItem.objects.create(
            programacao=programacao_original,
            meta=self.meta,
            concluido=False,
            concluido_em=timezone.now(),
            cancelada=False,
            nao_realizada_justificada=False,
        )
        programacao_remarcada = Programacao.objects.create(
            data=date(2026, 8, 11),
            unidade=self.unidade,
            criado_por=self.user,
        )
        ProgramacaoItem.objects.create(
            programacao=programacao_remarcada,
            meta=self.meta,
            concluido=True,
            concluido_em=timezone.now(),
            cancelada=False,
            nao_realizada_justificada=False,
            remarcado_de=item_original,
        )

        response = self.client.post(reverse("relatorios:programacao_encerrar_mes"), {"mes": "2026-08"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        programacao_original.refresh_from_db()
        programacao_remarcada.refresh_from_db()
        self.assertTrue(programacao_original.concluida)
        self.assertTrue(programacao_remarcada.concluida)

        response = self.client.get(reverse("relatorios:programacao"), {"report_tab": "encerradas"})
        periodo = next(row for row in response.context["programacoes_encerradas_periodos"] if row["mes"].date() == date(2026, 8, 1))
        self.assertEqual(periodo["total_atividades"], 1)
        self.assertEqual(periodo["nao_realizadas"], 0)
        self.assertEqual(periodo["concluidas"], 1)

    @override_settings(META_EXPEDIENTE_ID=777909)
    def test_encerrar_programacao_mes_ignora_expediente_administrativo_pendente(self):
        meta_expediente = Meta.objects.create(
            id=777909,
            unidade_criadora=self.unidade,
            atividade=None,
            titulo="Expediente administrativo",
            descricao="",
            quantidade_alvo=0,
            criado_por=self.user,
        )
        programacao = Programacao.objects.create(
            data=date(2026, 7, 10),
            unidade=self.unidade,
            criado_por=self.user,
        )
        item_expediente = ProgramacaoItem.objects.create(
            programacao=programacao,
            meta=meta_expediente,
            concluido=False,
            concluido_em=None,
            cancelada=False,
            nao_realizada_justificada=False,
        )

        response = self.client.post(reverse("relatorios:programacao_encerrar_mes"), {"mes": "2026-07"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        programacao.refresh_from_db()
        item_expediente.refresh_from_db()
        self.assertTrue(programacao.concluida)
        self.assertTrue(item_expediente.concluido)
        self.assertIsNotNone(item_expediente.concluido_em)
        self.assertEqual(item_expediente.concluido_por, self.user)

        response = self.client.get(reverse("relatorios:programacao"), {"report_tab": "encerradas"})
        periodo = next(row for row in response.context["programacoes_encerradas_periodos"] if row["mes"].date() == date(2026, 7, 1))
        self.assertEqual(periodo["total_atividades"], 0)
        self.assertEqual(periodo["pendentes"], 0)

    def test_encerrar_programacao_mes_ignora_item_encerrado_automaticamente(self):
        programacao = Programacao.objects.create(
            data=date(2026, 7, 10),
            unidade=self.unidade,
            criado_por=self.user,
        )
        ProgramacaoItem.objects.create(
            programacao=programacao,
            meta=self.meta,
            concluido=False,
            concluido_em=None,
            cancelada=False,
            nao_realizada_justificada=False,
            observacao=f"Encerrado automaticamente ao encerrar a meta. {ENCERRADA_AUTOMATICAMENTE_MARKER}",
        )

        response = self.client.post(reverse("relatorios:programacao_encerrar_mes"), {"mes": "2026-07"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        programacao.refresh_from_db()
        self.assertTrue(programacao.concluida)

        response = self.client.get(reverse("relatorios:programacao"), {"report_tab": "encerradas"})
        periodo = next(row for row in response.context["programacoes_encerradas_periodos"] if row["mes"].date() == date(2026, 7, 1))
        self.assertEqual(periodo["pendentes"], 0)
        self.assertEqual(periodo["encerradas_auto"], 1)
        self.assertEqual(periodo["percentual_solucionado"], 100)
