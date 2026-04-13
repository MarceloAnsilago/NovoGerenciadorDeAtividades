from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from atividades.models import Area, Atividade
from core.models import No
from metas.models import Meta, MetaAlocacao


class MetaTitleSyncTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="tester", password="123456")
        self.unidade = No.objects.create(nome="Unidade A", tipo="setor")
        self.area, _ = Area.objects.get_or_create(code=Area.CODE_OUTROS, defaults={"nome": "Outros"})

    def test_display_titulo_prefere_atividade(self):
        atividade = Atividade.objects.create(
            titulo="Barreira",
            descricao="",
            area=self.area,
            unidade_origem=self.unidade,
            criado_por=self.user,
        )
        meta = Meta.objects.create(
            unidade_criadora=self.unidade,
            atividade=atividade,
            titulo="Titulo manual",
            descricao="",
            quantidade_alvo=10,
            criado_por=self.user,
        )
        self.assertEqual(meta.display_titulo, "Barreira")

    def test_renomear_atividade_sincroniza_titulo_da_meta(self):
        atividade = Atividade.objects.create(
            titulo="Barreira",
            descricao="",
            area=self.area,
            unidade_origem=self.unidade,
            criado_por=self.user,
        )
        meta = Meta.objects.create(
            unidade_criadora=self.unidade,
            atividade=atividade,
            titulo="Titulo temporario",
            descricao="",
            quantidade_alvo=10,
            criado_por=self.user,
        )
        self.assertEqual(meta.titulo, "Barreira")

        atividade.titulo = "Barreiras"
        atividade.save()

        meta.refresh_from_db()
        self.assertEqual(meta.titulo, "Barreiras")
        self.assertEqual(meta.display_titulo, "Barreiras")


class MetaEditQuantidadeTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="editor", password="123456")
        self.unidade = No.objects.create(nome="Unidade B", tipo="setor")
        self.area, _ = Area.objects.get_or_create(code="AREA_TESTE", defaults={"nome": "Area Teste"})
        self.atividade = Atividade.objects.create(
            titulo="Fiscalizacao",
            descricao="",
            area=self.area,
            unidade_origem=self.unidade,
            criado_por=self.user,
        )
        self.meta = Meta.objects.create(
            unidade_criadora=self.unidade,
            atividade=self.atividade,
            titulo="Fiscalizacao",
            descricao="meta de teste",
            quantidade_alvo=20,
            criado_por=self.user,
            data_limite=date(2026, 12, 31),
        )
        MetaAlocacao.objects.create(
            meta=self.meta,
            unidade=self.unidade,
            quantidade_alocada=15,
            atribuida_por=self.user,
        )

        self.client.force_login(self.user)
        session = self.client.session
        session["contexto_atual"] = self.unidade.id
        session.save()

    def test_permite_reduzir_quantidade_ate_total_alocado(self):
        url = reverse("metas:editar", args=[self.meta.id])
        payload = {
            "data_inicio": "",
            "data_limite": "2026-12-31",
            "quantidade_alvo": "15",
            "descricao": self.meta.descricao,
        }

        response = self.client.post(f"{url}?next=/metas/atividades/", data=payload)

        self.assertRedirects(response, "/metas/atividades/", fetch_redirect_response=False)
        self.meta.refresh_from_db()
        self.assertEqual(self.meta.quantidade_alvo, 15)

    def test_bloqueia_reducao_abaixo_do_total_alocado(self):
        url = reverse("metas:editar", args=[self.meta.id])
        payload = {
            "data_inicio": "",
            "data_limite": "2026-12-31",
            "quantidade_alvo": "14",
            "descricao": self.meta.descricao,
        }

        response = self.client.post(f"{url}?next=/metas/atividades/", data=payload)

        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertIn("quantidade_alvo", form.errors)
        self.assertContains(response, "total alocado (15)")
        self.meta.refresh_from_db()
        self.assertEqual(self.meta.quantidade_alvo, 20)


class MetaAutoAllocationFlowTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="gestor_meta", password="123456")
        self.unidade = No.objects.create(nome="Unidade Folha", tipo="setor")
        self.area, _ = Area.objects.get_or_create(code="AREA_AUTO", defaults={"nome": "Area Auto"})
        self.atividade = Atividade.objects.create(
            titulo="Operacao Auto",
            descricao="",
            area=self.area,
            unidade_origem=self.unidade,
            criado_por=self.user,
        )

        self.client.force_login(self.user)
        session = self.client.session
        session["contexto_atual"] = self.unidade.id
        session.save()

    def test_criacao_em_unidade_sem_filhos_gera_alocacao_automatica(self):
        response = self.client.post(
            reverse("metas:definir-meta", args=[self.atividade.id]),
            data={
                "data_inicio": "2026-01-01",
                "data_limite": "2026-12-31",
                "quantidade_alvo": "10",
                "descricao": "Meta auto",
            },
        )

        self.assertRedirects(
            response,
            reverse("metas:definir-meta", args=[self.atividade.id]),
            fetch_redirect_response=False,
        )
        meta = Meta.objects.get(atividade=self.atividade)
        self.assertEqual(meta.modo_alocacao, Meta.MODO_ALOCACAO_AUTO)
        aloc = MetaAlocacao.objects.get(meta=meta, unidade=self.unidade)
        self.assertEqual(aloc.quantidade_alocada, 10)

    def test_edicao_de_meta_automatica_sincroniza_alocacao(self):
        meta = Meta.objects.create(
            unidade_criadora=self.unidade,
            atividade=self.atividade,
            titulo=self.atividade.titulo,
            descricao="Meta auto",
            quantidade_alvo=20,
            criado_por=self.user,
            data_limite=date(2026, 12, 31),
            modo_alocacao=Meta.MODO_ALOCACAO_AUTO,
        )
        MetaAlocacao.objects.create(
            meta=meta,
            unidade=self.unidade,
            quantidade_alocada=20,
            atribuida_por=self.user,
        )

        response = self.client.post(
            f"{reverse('metas:editar', args=[meta.id])}?next=/metas/",
            data={
                "data_inicio": "",
                "data_limite": "2026-12-31",
                "quantidade_alvo": "14",
                "descricao": "Meta auto ajustada",
            },
        )

        self.assertRedirects(response, "/metas/", fetch_redirect_response=False)
        meta.refresh_from_db()
        aloc = MetaAlocacao.objects.get(meta=meta, unidade=self.unidade)
        self.assertEqual(meta.quantidade_alvo, 14)
        self.assertEqual(aloc.quantidade_alocada, 14)

    def test_meta_automatica_pode_virar_manual_quando_unidade_ganha_filho(self):
        meta = Meta.objects.create(
            unidade_criadora=self.unidade,
            atividade=self.atividade,
            titulo=self.atividade.titulo,
            descricao="Meta auto",
            quantidade_alvo=10,
            criado_por=self.user,
            data_limite=date(2026, 12, 31),
            modo_alocacao=Meta.MODO_ALOCACAO_AUTO,
        )
        MetaAlocacao.objects.create(
            meta=meta,
            unidade=self.unidade,
            quantidade_alocada=10,
            atribuida_por=self.user,
        )
        filho = No.objects.create(nome="Equipe Nova", tipo="setor", parent=self.unidade)

        response = self.client.post(
            reverse("metas:atribuir-meta", args=[meta.id]),
            data={
                f"quantity_{self.unidade.id}": "4",
                f"obs_{self.unidade.id}": "",
                f"quantity_{filho.id}": "6",
                f"obs_{filho.id}": "Redistribuida",
            },
        )

        self.assertRedirects(response, reverse("metas:metas-unidade"), fetch_redirect_response=False)
        meta.refresh_from_db()
        self.assertEqual(meta.modo_alocacao, Meta.MODO_ALOCACAO_MANUAL)
        self.assertTrue(MetaAlocacao.objects.filter(meta=meta, unidade=self.unidade, quantidade_alocada=4).exists())
        self.assertTrue(MetaAlocacao.objects.filter(meta=meta, unidade=filho, quantidade_alocada=6).exists())
