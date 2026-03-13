import json
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from atividades.models import Area, Atividade
from core.models import No
from metas.models import Meta
from programar.models import Programacao, ProgramacaoItem
from veiculos.models import Veiculo


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
        self.assertContains(response, f"Item #{self.item.id}")

    @override_settings(META_EXPEDIENTE_ID=321)
    def test_nao_realizadas_inclui_contexto_do_modal_com_veiculos(self):
        Veiculo.objects.create(
            unidade=self.unidade,
            nome="Caminhonete",
            placa="ABC1D23",
            ativo=True,
        )

        response = self.client.get(reverse("minhas_metas:nao-realizadas"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["META_EXPEDIENTE_ID"], 321)
        veiculos = json.loads(response.context["VEICULOS_ATIVOS_JSON"])
        self.assertEqual(len(veiculos), 1)
        self.assertEqual(veiculos[0]["nome"], "Caminhonete")
        self.assertEqual(veiculos[0]["placa"], "ABC1D23")

    def test_revisar_status_aponta_para_item_remarcado_mais_recente(self):
        programacao_remarcada = Programacao.objects.create(
            data=date(2026, 3, 12),
            unidade=self.unidade,
            criado_por=self.user,
        )
        item_remarcado = ProgramacaoItem.objects.create(
            programacao=programacao_remarcada,
            meta=self.meta,
            concluido=True,
            concluido_em=timezone.now(),
            remarcado_de=self.item,
        )

        response = self.client.get(reverse("minhas_metas:nao-realizadas"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            reverse("programar:concluir-item-form", args=[item_remarcado.id]),
        )
        self.assertNotContains(
            response,
            reverse("programar:concluir-item-form", args=[self.item.id]),
        )
