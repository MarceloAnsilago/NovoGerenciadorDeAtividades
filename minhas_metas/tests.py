import json
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from atividades.models import Area, Atividade
from core.models import No
from metas.models import Meta, MetaAlocacao
from programar.models import Programacao, ProgramacaoItem
from programar.status import ENCERRADA_AUTOMATICAMENTE_MARKER
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

    def test_print_renderiza_pagina_agrupada_do_mes(self):
        response = self.client.get(
            reverse("minhas_metas:nao-realizadas"),
            {"month": "2026-03", "print": "1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "minhas_metas/nao_realizadas_print.html")
        self.assertContains(response, "Atividades nao realizadas e atrasadas no periodo selecionado")
        self.assertContains(response, self.meta.display_titulo)
        self.assertContains(response, "Periodo:")

        grupos = response.context["nao_realizadas_grupos"]
        self.assertEqual(len(grupos), 1)
        self.assertEqual(grupos[0]["meta_id"], self.meta.id)

    def test_nao_realizadas_inclui_pendentes_atrasadas_no_mes(self):
        data_atrasada = timezone.localdate() - timedelta(days=1)
        programacao_atrasada = Programacao.objects.create(
            data=data_atrasada,
            unidade=self.unidade,
            criado_por=self.user,
        )
        item_atrasado = ProgramacaoItem.objects.create(
            programacao=programacao_atrasada,
            meta=self.meta,
            concluido=False,
            concluido_em=None,
            nao_realizada_justificada=False,
            observacao="Pendente atrasada",
        )

        response = self.client.get(
            reverse("minhas_metas:nao-realizadas"),
            {"month": f"{data_atrasada.year}-{data_atrasada.month:02d}"},
        )

        self.assertEqual(response.status_code, 200)
        item_ids = {item["item_id"] for item in response.context["nao_realizadas"]}
        self.assertIn(item_atrasado.id, item_ids)
        atrasado = next(item for item in response.context["nao_realizadas"] if item["item_id"] == item_atrasado.id)
        self.assertEqual(atrasado["status"], "Atrasada")
        self.assertContains(response, "Pendente atrasada")

    def test_bloqueios_encerramento_inclui_pendentes_do_mes_mesmo_nao_atrasadas(self):
        data_futura = timezone.localdate() + timedelta(days=10)
        programacao_futura = Programacao.objects.create(
            data=data_futura,
            unidade=self.unidade,
            criado_por=self.user,
        )
        item_pendente = ProgramacaoItem.objects.create(
            programacao=programacao_futura,
            meta=self.meta,
            concluido=False,
            concluido_em=None,
            nao_realizada_justificada=False,
            observacao="Pendente ainda nao atrasada",
        )

        month_key = f"{data_futura.year}-{data_futura.month:02d}"
        response = self.client.get(
            reverse("minhas_metas:nao-realizadas"),
            {"month": month_key, "bloqueios_encerramento": "1"},
        )

        self.assertEqual(response.status_code, 200)
        item_ids = {item["item_id"] for item in response.context["nao_realizadas"]}
        self.assertIn(item_pendente.id, item_ids)
        pendente = next(item for item in response.context["nao_realizadas"] if item["item_id"] == item_pendente.id)
        self.assertEqual(pendente["status"], "Pendente")
        self.assertContains(response, "Atividades que impedem o encerramento")
        self.assertContains(response, "Pendente ainda nao atrasada")

    def test_nao_realizadas_nao_inclui_encerradas_automaticamente_como_atrasadas(self):
        data_atrasada = timezone.localdate() - timedelta(days=1)
        programacao_atrasada = Programacao.objects.create(
            data=data_atrasada,
            unidade=self.unidade,
            criado_por=self.user,
        )
        item_encerrado = ProgramacaoItem.objects.create(
            programacao=programacao_atrasada,
            meta=self.meta,
            concluido=False,
            concluido_em=None,
            nao_realizada_justificada=False,
            observacao=f"Encerrado automaticamente ao encerrar a meta. {ENCERRADA_AUTOMATICAMENTE_MARKER}",
        )

        response = self.client.get(
            reverse("minhas_metas:nao-realizadas"),
            {"month": f"{data_atrasada.year}-{data_atrasada.month:02d}"},
        )

        self.assertEqual(response.status_code, 200)
        item_ids = {item["item_id"] for item in response.context["nao_realizadas"]}
        self.assertNotIn(item_encerrado.id, item_ids)
        self.assertNotContains(response, "Encerrado automaticamente ao encerrar a meta")

    def test_nao_realizadas_exclui_itens_cancelados(self):
        self.item.cancelada = True
        self.item.save(update_fields=["cancelada"])

        response = self.client.get(reverse("minhas_metas:nao-realizadas"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nenhuma atividade")


class MapaAtividadesViewTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="tester_mapa", password="123456")
        self.unidade = No.objects.create(nome="ULSAV Mapa", tipo="setor")
        self.area = Area.objects.create(code="AREA_MAPA", nome="Area Mapa")
        self.atividade = Atividade.objects.create(
            titulo="Fiscalizacao por diligencia",
            descricao="",
            area=self.area,
            unidade_origem=self.unidade,
            criado_por=self.user,
        )
        self.meta = Meta.objects.create(
            unidade_criadora=self.unidade,
            atividade=self.atividade,
            titulo="Titulo temporario",
            descricao="meta de mapa",
            quantidade_alvo=3,
            data_inicio=date(2026, 3, 1),
            data_limite=date(2026, 3, 31),
            criado_por=self.user,
        )
        MetaAlocacao.objects.create(
            meta=self.meta,
            unidade=self.unidade,
            quantidade_alocada=3,
            atribuida_por=self.user,
        )
        self.programacao = Programacao.objects.create(
            data=date(2026, 3, 11),
            unidade=self.unidade,
            criado_por=self.user,
        )
        self.item_concluido = ProgramacaoItem.objects.create(
            programacao=self.programacao,
            meta=self.meta,
            concluido=True,
            concluido_em=timezone.now(),
        )

        self.client.force_login(self.user)
        session = self.client.session
        session["contexto_atual"] = self.unidade.id
        session.save()

    def test_mapa_gera_quadrados_pelas_diligencias_e_marca_concluidas_programadas(self):
        response = self.client.get(
            reverse("minhas_metas:mapa-atividades"),
            {"inicio": "2026-03-01", "fim": "2026-03-31", "status": ""},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_atividades"], 3)
        self.assertEqual(response.context["concluidas"], 1)

        rows = response.context["rows"]
        self.assertEqual(len(rows), 1)
        atividades = rows[0]["atividades"]
        self.assertEqual(len(atividades), 3)
        self.assertEqual(atividades[0]["item_id"], self.item_concluido.id)
        self.assertTrue(atividades[0]["concluido"])
        self.assertIsNone(atividades[1]["item_id"])
        self.assertFalse(atividades[1]["concluido"])
        self.assertIsNone(atividades[2]["item_id"])

        self.assertContains(response, "Diligencias:")
        self.assertContains(response, "Diligencia nao programada", count=2)

    def test_mapa_status_concluidas_filtra_quadrados_sem_levar_nao_programadas(self):
        response = self.client.get(
            reverse("minhas_metas:mapa-atividades"),
            {"inicio": "2026-03-01", "fim": "2026-03-31", "status": "concluidas"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_atividades"], 1)
        self.assertEqual(response.context["concluidas"], 1)

        rows = response.context["rows"]
        self.assertEqual(len(rows), 1)
        atividades = rows[0]["atividades"]
        self.assertEqual(len(atividades), 1)
        self.assertEqual(atividades[0]["item_id"], self.item_concluido.id)
        self.assertTrue(atividades[0]["concluido"])
        self.assertNotContains(response, "Diligencia nao programada")

    def test_mapa_status_em_andamento_inclui_diligencias_nao_programadas(self):
        response = self.client.get(
            reverse("minhas_metas:mapa-atividades"),
            {"inicio": "2026-03-01", "fim": "2026-03-31", "status": "em_andamento"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_atividades"], 2)
        self.assertEqual(response.context["concluidas"], 0)

        rows = response.context["rows"]
        self.assertEqual(len(rows), 1)
        atividades = rows[0]["atividades"]
        self.assertEqual(len(atividades), 2)
        self.assertIsNone(atividades[0]["item_id"])
        self.assertIsNone(atividades[1]["item_id"])
        self.assertContains(response, "Diligencia nao programada", count=2)

    def test_mapa_opcoes_de_atividade_refletem_status_filtrado(self):
        outra_atividade = Atividade.objects.create(
            titulo="Fiscalizacao sem conclusao",
            descricao="",
            area=self.area,
            unidade_origem=self.unidade,
            criado_por=self.user,
        )
        outra_meta = Meta.objects.create(
            unidade_criadora=self.unidade,
            atividade=outra_atividade,
            titulo="Titulo temporario",
            descricao="meta sem conclusao",
            quantidade_alvo=1,
            data_inicio=date(2026, 3, 1),
            data_limite=date(2026, 3, 31),
            criado_por=self.user,
        )
        MetaAlocacao.objects.create(
            meta=outra_meta,
            unidade=self.unidade,
            quantidade_alocada=1,
            atribuida_por=self.user,
        )

        response = self.client.get(
            reverse("minhas_metas:mapa-atividades"),
            [
                ("inicio", "2026-03-01"),
                ("fim", "2026-03-31"),
                ("status", "concluidas"),
                ("filtrar_atividades", "1"),
                ("meta", str(self.meta.id)),
                ("meta", str(outra_meta.id)),
            ],
        )

        self.assertEqual(response.status_code, 200)
        opcoes_ids = {opcao["id"] for opcao in response.context["atividades_opcoes"]}
        self.assertIn(self.meta.id, opcoes_ids)
        self.assertNotIn(outra_meta.id, opcoes_ids)
        self.assertEqual(response.context["total_atividades"], 1)

    def test_mapa_troca_de_status_recalcula_atividades_marcadas(self):
        outra_atividade = Atividade.objects.create(
            titulo="Fiscalizacao pendente",
            descricao="",
            area=self.area,
            unidade_origem=self.unidade,
            criado_por=self.user,
        )
        outra_meta = Meta.objects.create(
            unidade_criadora=self.unidade,
            atividade=outra_atividade,
            titulo="Titulo temporario",
            descricao="meta pendente",
            quantidade_alvo=1,
            data_inicio=date(2026, 3, 1),
            data_limite=date(2026, 3, 31),
            criado_por=self.user,
        )
        MetaAlocacao.objects.create(
            meta=outra_meta,
            unidade=self.unidade,
            quantidade_alocada=1,
            atribuida_por=self.user,
        )

        response = self.client.get(
            reverse("minhas_metas:mapa-atividades"),
            [
                ("inicio", "2026-03-01"),
                ("fim", "2026-03-31"),
                ("status", "concluidas"),
                ("status_anterior", "em_andamento"),
                ("filtrar_atividades", "1"),
                ("meta", str(outra_meta.id)),
            ],
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_atividades"], 1)
        self.assertEqual(response.context["rows"][0]["meta_id"], self.meta.id)
        opcoes = response.context["atividades_opcoes"]
        self.assertEqual(len(opcoes), 1)
        self.assertEqual(opcoes[0]["id"], self.meta.id)
        self.assertTrue(opcoes[0]["selected"])

    def test_mapa_filtro_area_usa_mesma_regra_inclusiva_de_atividades(self):
        area_animal_vegetal = Area.objects.create(
            code=Area.CODE_ANIMAL_VEGETAL,
            nome="Animal e Vegetal",
        )
        atividade_mista = Atividade.objects.create(
            titulo="Fiscalizacao mista",
            descricao="",
            area=area_animal_vegetal,
            unidade_origem=self.unidade,
            criado_por=self.user,
        )
        meta_mista = Meta.objects.create(
            unidade_criadora=self.unidade,
            atividade=atividade_mista,
            titulo="Titulo temporario",
            descricao="meta mista",
            quantidade_alvo=1,
            data_inicio=date(2026, 3, 1),
            data_limite=date(2026, 3, 31),
            criado_por=self.user,
        )
        MetaAlocacao.objects.create(
            meta=meta_mista,
            unidade=self.unidade,
            quantidade_alocada=1,
            atribuida_por=self.user,
        )

        response = self.client.get(
            reverse("minhas_metas:mapa-atividades"),
            {"inicio": "2026-03-01", "fim": "2026-03-31", "status": "", "area": Area.CODE_ANIMAL},
        )

        self.assertEqual(response.status_code, 200)
        opcoes_ids = {opcao["id"] for opcao in response.context["atividades_opcoes"]}
        self.assertIn(meta_mista.id, opcoes_ids)
        self.assertNotIn(self.meta.id, opcoes_ids)

        response = self.client.get(
            reverse("minhas_metas:mapa-atividades"),
            {"inicio": "2026-03-01", "fim": "2026-03-31", "status": "", "area": Area.CODE_VEGETAL},
        )

        self.assertEqual(response.status_code, 200)
        opcoes_ids = {opcao["id"] for opcao in response.context["atividades_opcoes"]}
        self.assertIn(meta_mista.id, opcoes_ids)
        self.assertNotIn(self.meta.id, opcoes_ids)
