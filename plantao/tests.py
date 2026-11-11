from datetime import date
import re

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.models import No, UserProfile
from descanso.models import Descanso
from servidores.models import Servidor

from .models import Plantao, Semana, SemanaServidor


@override_settings(CSRF_COOKIE_HTTPONLY=True)
class PlantaoExclusaoCsrfTests(TestCase):
    def setUp(self):
        self.unidade = No.objects.create(nome="Unidade Exclusao")
        self.user = User.objects.create_user(username="criador")
        UserProfile.objects.create(user=self.user, unidade=self.unidade)
        self.plantao = Plantao.objects.create(
            inicio=date(2026, 10, 1), fim=date(2026, 11, 1),
            criado_por=self.user, unidade=self.unidade,
        )
        self.url = reverse("plantao:plantao_excluir", args=[self.plantao.pk])
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.user)

    def page_token(self):
        response = self.client.get(reverse("plantao:lista_plantao"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.cookies["csrftoken"]["httponly"])
        match = re.search(r'const csrftoken = "([a-zA-Z0-9]+)";', response.content.decode())
        self.assertIsNotNone(match)
        return match.group(1)

    def test_criador_exclui_com_token_da_pagina_e_cookie_httponly(self):
        response = self.client.post(self.url, HTTP_X_CSRFTOKEN=self.page_token())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        self.assertFalse(Plantao.objects.filter(pk=self.plantao.pk).exists())

    def test_sem_token_continua_bloqueado(self):
        self.page_token()
        self.assertEqual(self.client.post(self.url).status_code, 403)
        self.assertTrue(Plantao.objects.filter(pk=self.plantao.pk).exists())

    def test_token_valido_nao_libera_exclusao_por_outro_usuario(self):
        outro = User.objects.create_user(username="outro")
        UserProfile.objects.create(user=outro, unidade=self.unidade)
        self.client.force_login(outro)
        response = self.client.post(self.url, HTTP_X_CSRFTOKEN=self.page_token())
        self.assertEqual(response.status_code, 403)
        self.assertIn("erro", response.json())
        self.assertTrue(Plantao.objects.filter(pk=self.plantao.pk).exists())

    def test_get_nao_exclui(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertTrue(Plantao.objects.filter(pk=self.plantao.pk).exists())


class PlantaoServidorAtivoTests(TestCase):
    def setUp(self):
        self.unidade = No.objects.create(nome="Unidade Teste")
        self.user = User.objects.create_user(username="tester", password="secret123")
        UserProfile.objects.create(user=self.user, unidade=self.unidade)
        self.client.force_login(self.user)

    def test_lista_plantao_nao_exibe_servidor_inativo(self):
        ativo = Servidor.objects.create(unidade=self.unidade, nome="Servidor Ativo", ativo=True)
        inativo = Servidor.objects.create(unidade=self.unidade, nome="Servidor Inativo", ativo=False)
        Descanso.objects.create(
            servidor=inativo,
            tipo=Descanso.Tipo.RECESSO,
            data_inicio=date(2026, 10, 4),
            data_fim=date(2026, 10, 10),
        )

        response = self.client.get(
            reverse("plantao:lista_plantao"),
            {
                "data_inicial": "2026-10-04",
                "data_final": "2026-10-10",
                "duracao_ciclo": "7",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, ativo.nome)
        self.assertNotContains(response, inativo.nome)

    def test_post_ignora_servidor_inativo_enviado_manualmente(self):
        ativo = Servidor.objects.create(unidade=self.unidade, nome="Servidor Ativo", ativo=True)
        inativo = Servidor.objects.create(unidade=self.unidade, nome="Servidor Inativo", ativo=False)

        response = self.client.post(
            reverse("plantao:lista_plantao"),
            {
                "data_inicial": "2026-10-04",
                "data_final": "2026-10-10",
                "dia_inicio_ciclo": "6",
                "duracao_ciclo": "7",
                "grupo_1": [str(ativo.pk), str(inativo.pk)],
            },
        )

        self.assertEqual(response.status_code, 302)
        plantao = Plantao.objects.get()
        servidores_ids = set(SemanaServidor.objects.filter(semana__plantao=plantao).values_list("servidor_id", flat=True))
        self.assertEqual(servidores_ids, {ativo.pk})

    def test_detalhe_plantao_salvo_oculta_servidor_inativo(self):
        ativo = Servidor.objects.create(unidade=self.unidade, nome="Servidor Ativo", ativo=True)
        inativo = Servidor.objects.create(unidade=self.unidade, nome="Servidor Inativo", ativo=False)
        plantao = Plantao.objects.create(
            inicio=date(2026, 10, 4),
            fim=date(2026, 10, 10),
            criado_por=self.user,
            unidade=self.unidade,
        )
        semana = Semana.objects.create(
            plantao=plantao,
            inicio=date(2026, 10, 4),
            fim=date(2026, 10, 10),
            ordem=1,
        )
        SemanaServidor.objects.create(semana=semana, servidor=ativo, ordem=1)
        SemanaServidor.objects.create(semana=semana, servidor=inativo, ordem=2)

        response = self.client.get(reverse("plantao:plantao_detalhe_fragment", args=[plantao.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, ativo.nome)
        self.assertNotContains(response, inativo.nome)
