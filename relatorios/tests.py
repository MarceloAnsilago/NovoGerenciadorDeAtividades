from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from atividades.models import Area, Atividade
from core.models import No
from metas.models import Meta
from programar.models import Programacao, ProgramacaoItem


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
        self.assertContains(response, f"Substituiu: 10/03/2026 - Item #{item_original.id}")
