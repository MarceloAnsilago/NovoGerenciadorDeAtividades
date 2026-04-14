from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import No, UserProfile
from descanso.models import Descanso

from .models import Servidor


class ServidorExclusaoTests(TestCase):
    def setUp(self):
        self.unidade = No.objects.create(nome="Unidade Teste")
        self.user = User.objects.create_user(username="tester", password="secret123")
        UserProfile.objects.create(user=self.user, unidade=self.unidade)
        self.client.force_login(self.user)

    def test_excluir_servidor_inativo_sem_vinculos(self):
        servidor = Servidor.objects.create(
            unidade=self.unidade,
            nome="Servidor Sem Vinculos",
            ativo=False,
        )

        response = self.client.post(reverse("servidores:excluir", args=[servidor.pk]), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Servidor.objects.filter(pk=servidor.pk).exists())

    def test_nao_exclui_servidor_inativo_com_vinculos(self):
        servidor = Servidor.objects.create(
            unidade=self.unidade,
            nome="Servidor Com Descanso",
            ativo=False,
        )
        Descanso.objects.create(
            servidor=servidor,
            tipo=Descanso.Tipo.RECESSO,
            data_inicio=date(2026, 1, 10),
            data_fim=date(2026, 1, 12),
        )

        response = self.client.post(reverse("servidores:excluir", args=[servidor.pk]), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Servidor.objects.filter(pk=servidor.pk).exists())

    def test_lista_inativos_exibe_bloqueio_e_exclusao_quando_couber(self):
        liberado = Servidor.objects.create(
            unidade=self.unidade,
            nome="Servidor Liberado",
            ativo=False,
        )
        bloqueado = Servidor.objects.create(
            unidade=self.unidade,
            nome="Servidor Bloqueado",
            ativo=False,
        )
        Descanso.objects.create(
            servidor=bloqueado,
            tipo=Descanso.Tipo.RECESSO,
            data_inicio=date(2026, 2, 1),
            data_fim=date(2026, 2, 3),
        )

        response = self.client.get(reverse("servidores:lista"), {"status": "inativos"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("servidores:excluir", args=[liberado.pk]))
        self.assertContains(response, "Vinculos: 1 descanso")
