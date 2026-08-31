from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import No, UserProfile
from descanso.models import Descanso
from servidores.models import Servidor

from .models import Plantao, Semana, SemanaServidor


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
