from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import No, UserProfile
from descanso.models import Descanso

from .models import Servidor
from metas.models import Meta
from programar.models import Programacao, ProgramacaoItem, ProgramacaoItemServidor


class ServidorInativacaoTests(TestCase):
    def setUp(self):
        self.unidade = No.objects.create(nome="Unidade")
        self.user = User.objects.create_superuser(username="admin", password="secret123")
        self.client.force_login(self.user)
        self.servidor = Servidor.objects.create(unidade=self.unidade, nome="Servidor")
        self.outro = Servidor.objects.create(unidade=self.unidade, nome="Outro")
        self.meta = Meta.objects.create(unidade_criadora=self.unidade, criado_por=self.user, titulo="Atividade teste")
        self.programacao = Programacao.objects.create(unidade=self.unidade, data=date(2026, 11, 12))
        self.url = reverse("servidores:inativar", args=[self.servidor.pk])

    def item(self, **status):
        item = ProgramacaoItem.objects.create(programacao=self.programacao, meta=self.meta, **status)
        ProgramacaoItemServidor.objects.create(item=item, servidor=self.servidor)
        return item

    def test_avisa_sem_alterar_e_confirma_removendo_apenas_vinculos_abertos(self):
        pendente = self.item()
        justificada = self.item(nao_realizada_justificada=True)
        concluida = self.item(concluido=True)
        cancelada = self.item(cancelada=True)
        ProgramacaoItemServidor.objects.create(item=pendente, servidor=self.outro)
        response = self.client.post(self.url)
        self.assertContains(response, "Remover vínculos e inativar")
        self.servidor.refresh_from_db()
        self.assertTrue(self.servidor.ativo)
        self.assertEqual(ProgramacaoItemServidor.objects.filter(servidor=self.servidor).count(), 4)
        response = self.client.post(self.url, {"confirmar_remocao": "1"})
        self.assertEqual(response.status_code, 302)
        self.servidor.refresh_from_db()
        self.assertFalse(self.servidor.ativo)
        self.assertSetEqual(set(ProgramacaoItemServidor.objects.filter(servidor=self.servidor).values_list("item_id", flat=True)), {concluida.pk, cancelada.pk})
        self.assertTrue(ProgramacaoItemServidor.objects.filter(item=pendente, servidor=self.outro).exists())
        self.assertTrue(ProgramacaoItem.objects.filter(pk=justificada.pk).exists())

    def test_sem_atividades_abertas_inativa_diretamente(self):
        self.item(concluido=True)
        self.assertEqual(self.client.post(self.url).status_code, 302)
        self.servidor.refresh_from_db()
        self.assertFalse(self.servidor.ativo)

    def test_nao_permite_inativar_servidor_de_outra_unidade(self):
        unidade = No.objects.create(nome="Outra unidade")
        user = User.objects.create_user(username="outro")
        UserProfile.objects.create(user=user, unidade=unidade)
        self.client.force_login(user)
        self.assertEqual(self.client.post(self.url, {"confirmar_remocao": "1"}).status_code, 404)
        self.servidor.refresh_from_db()
        self.assertTrue(self.servidor.ativo)

    def test_edicao_nao_contorna_confirmacao(self):
        self.item()
        response = self.client.post(reverse("servidores:editar", args=[self.servidor.pk]), {"nome": "Servidor"})
        self.assertContains(response, "Use a opção Inativar")
        self.servidor.refresh_from_db()
        self.assertTrue(self.servidor.ativo)


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
        self.assertContains(response, "Nao e possivel excluir. Vinculos: 1 descanso")
