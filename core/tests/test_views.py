from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from atividades.models import Atividade
from core.models import No, UserProfile
from core.utils import gerar_senha_provisoria


class RedefinirSenhaTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user(username="admin", email="admin@test.com")
        self.admin.set_password("admin123")
        self.admin.save()

        unidade = No.objects.create(nome="Unidade Teste")
        self.profile = UserProfile.objects.create(user=self.admin, unidade=unidade)

        permission = Permission.objects.get(codename="change_userprofile")
        self.admin.user_permissions.add(permission)

        self.client.login(username="admin", password="admin123")

    def test_redefinir_senha(self):
        url = reverse("core:redefinir_senha", args=[self.admin.id])
        response = self.client.post(url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["username"], self.admin.username)
        self.assertIn("senha_provisoria", data)


class PrimeiroAcessoLoginTests(TestCase):
    def setUp(self):
        unidade = No.objects.create(nome="Unidade Base")
        self.user = get_user_model().objects.create_user(username="novo_usuario", email="novo@example.com")
        self.user.set_unusable_password()
        self.user.save()
        token = gerar_senha_provisoria(8)
        UserProfile.objects.create(user=self.user, unidade=unidade, senha_provisoria=token, ativado=False)
        self.token = token

    def test_login_with_provisional_password_redirects_to_password_change(self):
        response = self.client.post(
            reverse("core:login"),
            {"username": self.user.username, "password": self.token},
            follow=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("core:trocar_senha_primeiro_acesso"))
        self.assertEqual(self.client.session.get("troca_user_id"), self.user.id)

    def test_primeiro_acesso_token_view_redirects_to_password_change(self):
        response = self.client.post(
            reverse("core:primeiro_acesso_token"),
            {"username": self.user.username, "token": self.token},
            follow=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("core:trocar_senha_primeiro_acesso"))

    def test_primeiro_acesso_token_ignores_case_and_whitespace(self):
        response = self.client.post(
            reverse("core:primeiro_acesso_token"),
            {"username": f"  {self.user.username.upper()}  ", "token": self.token},
            follow=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("core:trocar_senha_primeiro_acesso"))



class LoginViewNormalizationTests(TestCase):
    def setUp(self):
        self.unidade = No.objects.create(nome="Unidade Login")
        self.user = get_user_model().objects.create_user(
            username="Presidente",
            email="presidente@example.com",
            password="Presidente123",
        )
        UserProfile.objects.create(user=self.user, unidade=self.unidade, ativado=True)

    def test_login_with_trimmed_username(self):
        response = self.client.post(
            reverse("core:login"),
            {"username": "  Presidente  ", "password": "Presidente123"},
            follow=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("core:dashboard"))

    def test_login_case_insensitive_username(self):
        response = self.client.post(
            reverse("core:login"),
            {"username": "presidente", "password": "Presidente123"},
            follow=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("core:dashboard"))


class ForceDeleteProfileTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="root",
            email="root@example.com",
            password="rootpass",
        )
        self.client.force_login(self.admin)

        self.unidade = No.objects.create(nome="Unidade Force")
        self.target = get_user_model().objects.create_user(username="bloqueado", email="force@example.com")
        UserProfile.objects.create(user=self.target, unidade=self.unidade, ativado=True)

        Atividade.objects.create(
            titulo="Atividade Bloqueio",
            unidade_origem=self.unidade,
            criado_por=self.target,
        )

    def test_force_delete_removes_protected_relations(self):
        url = reverse("core:excluir_perfil", args=[self.target.id])

        # tentativa sem forcar continua bloqueada
        response = self.client.post(url, {"confirm": "1"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["status"], "bloqueado")

        # com force=1 deve limpar dependencias e excluir
        response_force = self.client.post(url, {"confirm": "1", "force": "1"})
        self.assertEqual(response_force.status_code, 200)
        data = response_force.json()
        self.assertEqual(data["status"], "excluido")
        self.assertTrue(data.get("force_used"))
        self.assertTrue(data.get("cleanup"))

        # o usuario e suas atividades protegidas devem desaparecer
        self.assertFalse(get_user_model().objects.filter(id=self.target.id).exists())
        self.assertFalse(Atividade.objects.filter(titulo="Atividade Bloqueio").exists())
