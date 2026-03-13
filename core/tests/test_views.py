from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from atividades.models import Area, Atividade
from core.models import No, UserProfile
from core.utils import gerar_senha_provisoria, get_unidade_atual_id
from metas.models import Meta
from programar.models import Programacao, ProgramacaoItem, ProgramacaoItemServidor
from servidores.models import Servidor


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


class AssumirUnidadeSessionSyncTests(TestCase):
    def setUp(self):
        self.root = No.objects.create(nome="Raiz")
        self.u1 = No.objects.create(nome="Unidade 1", parent=self.root)
        self.u2 = No.objects.create(nome="Unidade 2", parent=self.root)

        self.user = get_user_model().objects.create_user(
            username="gestor_unidade",
            email="gestor@example.com",
            password="gestor123",
        )
        UserProfile.objects.create(user=self.user, unidade=self.root, ativado=True)

        perm = Permission.objects.get(codename="assumir_unidade")
        self.user.user_permissions.add(perm)
        self.client.force_login(self.user)

    def test_assumir_unidade_substitui_contexto_legado(self):
        session = self.client.session
        session["contexto"] = {"tipo": "unidade", "id": self.u1.id}
        session["contexto_atual"] = self.u1.id
        session["contexto_nome"] = self.u1.nome
        session.save()

        response = self.client.get(reverse("core:assumir_unidade", args=[self.u2.id]), follow=False)
        self.assertEqual(response.status_code, 302)

        session = self.client.session
        self.assertEqual(session.get("contexto_atual"), self.u2.id)
        self.assertEqual(session.get("contexto_nome"), self.u2.nome)
        self.assertEqual(session.get("unidade_id"), self.u2.id)
        self.assertEqual(session.get("contexto", {}).get("id"), self.u2.id)
        self.assertEqual(get_unidade_atual_id(response.wsgi_request), self.u2.id)

    def test_voltar_contexto_limpa_chaves_de_sessao(self):
        session = self.client.session
        session["contexto"] = {"tipo": "unidade", "id": self.u2.id}
        session["unidade_id"] = self.u2.id
        session["contexto_atual"] = self.u2.id
        session["contexto_nome"] = self.u2.nome
        session.save()

        response = self.client.get(reverse("core:voltar_contexto"), follow=False)
        self.assertEqual(response.status_code, 302)

        session = self.client.session
        self.assertNotIn("contexto", session)
        self.assertNotIn("unidade_id", session)
        self.assertNotIn("contexto_atual", session)
        self.assertNotIn("contexto_nome", session)


class DashboardServidorRemarcacaoTests(TestCase):
    def setUp(self):
        self.unidade = No.objects.create(nome="Unidade Dashboard")
        self.user = get_user_model().objects.create_user(
            username="dashboard_srv",
            email="dashboard@example.com",
            password="secret123",
        )
        UserProfile.objects.create(user=self.user, unidade=self.unidade, ativado=True)
        self.area = Area.objects.create(code="AREA_DASH", nome="Area Dashboard")
        self.atividade = Atividade.objects.create(
            titulo="Fiscalizacao remarcada",
            unidade_origem=self.unidade,
            area=self.area,
            criado_por=self.user,
        )
        self.meta = Meta.objects.create(
            unidade_criadora=self.unidade,
            atividade=self.atividade,
            titulo="Meta dashboard",
            descricao="",
            quantidade_alvo=2,
            criado_por=self.user,
        )
        self.servidor = Servidor.objects.create(unidade=self.unidade, nome="Servidor Dashboard", ativo=True)
        self.client.force_login(self.user)
        session = self.client.session
        session["contexto_atual"] = self.unidade.id
        session.save()

    def test_dashboard_servidor_exibe_origem_da_substituicao(self):
        programacao_origem = Programacao.objects.create(
            data=date(2026, 3, 10),
            unidade=self.unidade,
            criado_por=self.user,
        )
        item_origem = ProgramacaoItem.objects.create(
            programacao=programacao_origem,
            meta=self.meta,
            concluido=False,
            concluido_em=timezone.now(),
            nao_realizada_justificada=False,
            observacao="Nao realizada base",
        )
        programacao_destino = Programacao.objects.create(
            data=date(2026, 3, 12),
            unidade=self.unidade,
            criado_por=self.user,
        )
        item_destino = ProgramacaoItem.objects.create(
            programacao=programacao_destino,
            meta=self.meta,
            concluido=True,
            concluido_em=timezone.now(),
            remarcado_de=item_origem,
            observacao="Executada em substituicao",
        )
        ProgramacaoItemServidor.objects.create(item=item_destino, servidor=self.servidor)

        response = self.client.get(reverse("core:dashboard_servidor", args=[self.servidor.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Remarcada e concluida")
        self.assertContains(response, f"Substituiu: 10/03/2026 - Item #{item_origem.id}")
