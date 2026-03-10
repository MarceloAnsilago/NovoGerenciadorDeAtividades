from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from atividades.models import Area, Atividade
from core.models import No
from metas.models import Meta
from programar.models import Programacao, ProgramacaoItem


class NaoRealizadasViewTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="tester_mm", password="123456")
        self.unidade = No.objects.create(nome="ULSAV SMG", tipo="setor")
        self.area = Area.objects.create(code="AREA_MM", nome="Area Minhas Metas")
        self.atividade = Atividade.objects.create(
            titulo="Fiscalizacao Reversa-Lojas Agropecuarias",
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
            quantidade_alvo=1,
            criado_por=self.user,
        )
        self.programacao = Programacao.objects.create(
            data=date(2026, 3, 11),
            unidade=self.unidade,
            criado_por=self.user,
        )
        self.item = ProgramacaoItem.objects.create(
            programacao=self.programacao,
            meta=self.meta,
            concluido=False,
            concluido_em=timezone.now(),
            nao_realizada_justificada=False,
            observacao="Nao realizada",
        )

        self.client.force_login(self.user)
        session = self.client.session
        session["contexto_atual"] = self.unidade.id
        session.save()

    def test_nao_exibe_atividade_duplicada_quando_meta_usa_display_titulo(self):
        response = self.client.get(reverse("minhas_metas:nao-realizadas"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fiscalizacao Reversa-Lojas Agropecuarias", count=1)
        self.assertNotContains(response, "Atividade: Fiscalizacao Reversa-Lojas Agropecuarias")
