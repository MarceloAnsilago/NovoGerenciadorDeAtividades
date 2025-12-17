from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import No, UserProfile
from core.services.dashboard_queries import (
    get_dashboard_kpis,
    get_metas_por_unidade,
    get_atividades_por_area,
)
from metas.models import Meta, MetaAlocacao
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
        Atividade.objects.create(
            titulo="Atividade A",
            area=self.animal_area,
            unidade_origem=self.child,
            criado_por=self.user,
        )
        Atividade.objects.create(
            titulo="Atividade B",
            area=self.vegetal_area,
            unidade_origem=self.other,
            criado_por=self.user,
        )

        result = get_atividades_por_area(self.user, unidade_ids=[self.child.id, self.other.id])
        mapping = dict(zip(result["labels"], result["datasets"][0]["data"]))
        self.assertEqual(sum(mapping.values()), 2)

        scoped = get_atividades_por_area(self.user, unidade_ids=[self.child.id])
        scoped_mapping = dict(zip(scoped["labels"], scoped["datasets"][0]["data"]))
        self.assertEqual(sum(scoped_mapping.values()), 1)

        empty = get_atividades_por_area(self.user, unidade_ids=[])
        self.assertEqual(empty["datasets"][0]["data"], [])
