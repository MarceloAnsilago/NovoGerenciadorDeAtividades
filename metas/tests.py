from django.contrib.auth import get_user_model
from django.test import TestCase

from atividades.models import Area, Atividade
from core.models import No
from metas.models import Meta


class MetaTitleSyncTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="tester", password="123456")
        self.unidade = No.objects.create(nome="Unidade A", tipo="setor")
        self.area = Area.objects.create(code=Area.CODE_OUTROS, nome="Outros")

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
