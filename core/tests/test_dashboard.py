from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import No, UserProfile
from core.services.dashboard_queries import (
    get_dashboard_kpis,
    get_metas_por_unidade,
    get_atividades_por_area,
    get_progresso_mensal,
    get_programacoes_status_mensal,
)
from metas.models import Meta, MetaAlocacao, ProgressoMeta
from programar.models import Programacao, ProgramacaoItem
from servidores.models import Servidor
from atividades.models import Area, Atividade


class DashboardViewTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="tester", password="secret123")

    def test_login_required(self):
        response = self.client.get(reverse("core:dashboard"))
        self.assertEqual(response.status_code, 302)

    def test_dashboard_template_render(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("core:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/dashboard.html")


class DashboardBundleEndpointTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="bundle_user", password="secret123")
        self.root = No.objects.create(nome="Bundle", tipo="setor")
        UserProfile.objects.create(user=self.user, unidade=self.root)

    def test_dashboard_bundle_returns_expected_sections(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("core:dashboard_bundle"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertIn("kpis", payload)
        self.assertIn("metasPorUnidade", payload)
        self.assertIn("atividadesPorArea", payload)
        self.assertIn("progressoMensal", payload)
        self.assertIn("programacoesStatus", payload)
        self.assertIn("plantaoHeatmap", payload)
        self.assertIn("usoVeiculos", payload)
        self.assertIn("topServidores", payload)


class DashboardMetasPorUnidadeTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="manager", password="secret123")
        self.root = No.objects.create(nome="Supervisao", tipo="setor")
        UserProfile.objects.create(user=self.user, unidade=self.root)
        self.child = No.objects.create(nome="Equipe A", tipo="setor", parent=self.root)
        self.other = No.objects.create(nome="Equipe B", tipo="setor", parent=self.root)

        for code, label in Area.DEFAULT_AREAS:
            Area.objects.get_or_create(code=code, defaults={"nome": label})
        self.animal_area = Area.objects.get(code=Area.CODE_ANIMAL)
        self.vegetal_area = Area.objects.get(code=Area.CODE_VEGETAL)

        self.meta_ativa = Meta.objects.create(
            unidade_criadora=self.root,
            titulo="Meta ativa",
            descricao="",
            quantidade_alvo=10,
            criado_por=self.user,
        )
        MetaAlocacao.objects.create(
            meta=self.meta_ativa,
            unidade=self.child,
            quantidade_alocada=5,
            atribuida_por=self.user,
        )

        meta_encerrada = Meta.objects.create(
            unidade_criadora=self.root,
            titulo="Meta encerrada",
            descricao="",
            quantidade_alvo=3,
            criado_por=self.user,
            encerrada=True,
        )
        MetaAlocacao.objects.create(
            meta=meta_encerrada,
            unidade=self.other,
            quantidade_alocada=3,
            atribuida_por=self.user,
        )

        self.servidor_child = Servidor.objects.create(unidade=self.child, nome="Servidor A", ativo=True)
        self.servidor_other = Servidor.objects.create(unidade=self.other, nome="Servidor B", ativo=True)

    def test_consider_only_active_allocations(self):
        result = get_metas_por_unidade(self.user, unidade_ids=[self.child.id, self.other.id])
        self.assertEqual(result["labels"], ["Equipe A"])
        self.assertEqual(result["datasets"][0]["data"], [1])

    def test_empty_scope_returns_no_data(self):
        result = get_metas_por_unidade(self.user, unidade_ids=[])
        self.assertEqual(result["labels"], [])
        self.assertEqual(result["datasets"][0]["data"], [])

    def test_dashboard_kpis_respects_scope(self):
        result = get_dashboard_kpis(self.user, unidade_ids=[self.child.id])
        self.assertEqual(result["metas_ativas"], 1)
        self.assertEqual(result["percentual_metas_concluidas"], 0.0)
        self.assertEqual(result["servidores_ativos"], 1)

        # quando escopo vazio deve zerar
        empty = get_dashboard_kpis(self.user, unidade_ids=[])
        self.assertEqual(empty["metas_ativas"], 0)
        self.assertEqual(empty["servidores_ativos"], 0)

    def test_atividades_por_area_respects_scope(self):
        atividade_child = Atividade.objects.create(
            titulo="Atividade A",
            area=self.animal_area,
            unidade_origem=self.child,
            criado_por=self.user,
        )
        atividade_other = Atividade.objects.create(
            titulo="Atividade B",
            area=self.vegetal_area,
            unidade_origem=self.other,
            criado_por=self.user,
        )

        meta_child = Meta.objects.create(
            unidade_criadora=self.root,
            atividade=atividade_child,
            titulo="Meta A",
            descricao="",
            quantidade_alvo=1,
            criado_por=self.user,
        )
        MetaAlocacao.objects.create(
            meta=meta_child,
            unidade=self.child,
            quantidade_alocada=1,
            atribuida_por=self.user,
        )
        # A mesma meta alocada em mais de uma unidade do escopo nao pode duplicar os itens.
        MetaAlocacao.objects.create(
            meta=meta_child,
            unidade=self.other,
            quantidade_alocada=1,
            atribuida_por=self.user,
        )

        meta_other = Meta.objects.create(
            unidade_criadora=self.root,
            atividade=atividade_other,
            titulo="Meta B",
            descricao="",
            quantidade_alvo=1,
            criado_por=self.user,
        )
        MetaAlocacao.objects.create(
            meta=meta_other,
            unidade=self.other,
            quantidade_alocada=1,
            atribuida_por=self.user,
        )

        programacao_child = Programacao.objects.create(
            data=date(2026, 2, 5),
            unidade=self.child,
            criado_por=self.user,
        )
        ProgramacaoItem.objects.create(
            programacao=programacao_child,
            meta=meta_child,
            concluido=True,
        )

        programacao_other = Programacao.objects.create(
            data=date(2026, 2, 7),
            unidade=self.other,
            criado_por=self.user,
        )
        ProgramacaoItem.objects.create(
            programacao=programacao_other,
            meta=meta_other,
            concluido=False,
        )

        result = get_atividades_por_area(self.user, unidade_ids=[self.child.id, self.other.id])
        mapping = dict(zip(result["labels"], result["datasets"][0]["data"]))
        self.assertEqual(sum(mapping.values()), 2)

        scoped = get_atividades_por_area(self.user, unidade_ids=[self.child.id])
        scoped_mapping = dict(zip(scoped["labels"], scoped["datasets"][0]["data"]))
        self.assertEqual(sum(scoped_mapping.values()), 1)

        empty = get_atividades_por_area(self.user, unidade_ids=[])
        self.assertEqual(empty["datasets"][0]["data"], [])

    def test_programacoes_status_mensal_does_not_duplicate_items_for_multi_allocated_meta(self):
        atividade = Atividade.objects.create(
            titulo="Atividade Status",
            area=self.animal_area,
            unidade_origem=self.child,
            criado_por=self.user,
        )
        meta = Meta.objects.create(
            unidade_criadora=self.root,
            atividade=atividade,
            titulo="Meta Status",
            descricao="",
            quantidade_alvo=1,
            criado_por=self.user,
        )
        MetaAlocacao.objects.create(
            meta=meta,
            unidade=self.child,
            quantidade_alocada=1,
            atribuida_por=self.user,
        )
        MetaAlocacao.objects.create(
            meta=meta,
            unidade=self.other,
            quantidade_alocada=1,
            atribuida_por=self.user,
        )

        programacao = Programacao.objects.create(
            data=date(2026, 2, 10),
            unidade=self.child,
            criado_por=self.user,
        )
        ProgramacaoItem.objects.create(
            programacao=programacao,
            meta=meta,
            concluido=True,
        )

        result = get_programacoes_status_mensal(
            self.user,
            unidade_ids=[self.child.id, self.other.id],
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 28),
        )

        self.assertEqual(result["labels"], ["Fev/2026"])
        datasets = {dataset["label"]: dataset["data"] for dataset in result["datasets"]}
        self.assertEqual(datasets["ConcluÃ­das"], [1])
        self.assertEqual(datasets["Remarcadas e concluidas"], [0])
        self.assertEqual(datasets["NÃ£o realizadas"], [0])
        self.assertEqual(datasets["Pendentes"], [0])


class DashboardProgressoMensalTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="progresso", password="secret123")
        self.root = No.objects.create(nome="Regional", tipo="setor")
        UserProfile.objects.create(user=self.user, unidade=self.root)
        self.meta = Meta.objects.create(
            unidade_criadora=self.root,
            titulo="Meta de Progresso",
            descricao="",
            quantidade_alvo=100,
            criado_por=self.user,
        )
        self.alocacao = MetaAlocacao.objects.create(
            meta=self.meta,
            unidade=self.root,
            quantidade_alocada=100,
            atribuida_por=self.user,
        )

    @patch("core.services.dashboard_queries.timezone.localdate", return_value=date(2026, 2, 20))
    def test_current_month_range_returns_weekly_series(self, _mock_today):
        ProgressoMeta.objects.create(
            alocacao=self.alocacao,
            data=date(2026, 2, 3),
            quantidade=2,
            registrado_por=self.user,
        )
        ProgressoMeta.objects.create(
            alocacao=self.alocacao,
            data=date(2026, 2, 18),
            quantidade=4,
            registrado_por=self.user,
        )
        ProgressoMeta.objects.create(
            alocacao=self.alocacao,
            data=date(2026, 2, 27),
            quantidade=1,
            registrado_por=self.user,
        )

        result = get_progresso_mensal(
            self.user,
            unidade_ids=[self.root.id],
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 28),
        )

        expected_labels = [
            "26/01 a 01/02",
            "02/02 a 08/02",
            "09/02 a 15/02",
            "16/02 a 22/02",
            "23/02 a 01/03",
        ]
        self.assertEqual(result["datasets"][0]["label"], "Progresso semanal")
        self.assertEqual(result["labels"], expected_labels)
        self.assertEqual(result["datasets"][0]["data"], [0, 2, 0, 4, 1])

    @patch("core.services.dashboard_queries.timezone.localdate", return_value=date(2026, 2, 20))
    def test_non_current_month_range_keeps_monthly_series(self, _mock_today):
        ProgressoMeta.objects.create(
            alocacao=self.alocacao,
            data=date(2026, 1, 10),
            quantidade=3,
            registrado_por=self.user,
        )
        ProgressoMeta.objects.create(
            alocacao=self.alocacao,
            data=date(2026, 1, 22),
            quantidade=5,
            registrado_por=self.user,
        )

        result = get_progresso_mensal(
            self.user,
            unidade_ids=[self.root.id],
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )

        self.assertEqual(result["datasets"][0]["label"], "Progresso acumulado")
        self.assertEqual(result["labels"], ["Jan/2026"])
        self.assertEqual(result["datasets"][0]["data"], [8])
