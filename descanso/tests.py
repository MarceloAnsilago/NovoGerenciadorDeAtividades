from datetime import date
import re

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.models import No
from servidores.models import Servidor

from .models import Descanso, Feriado, FeriadoCadastro
from metas.models import Meta
from programar.models import Programacao, ProgramacaoItem
from .views import _build_descansos_unidade_context


class FeriadoAtividadeTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="feriados")
        self.unidade = No.objects.create(nome="Unidade Feriados")
        self.cadastro = FeriadoCadastro.objects.create(unidade=self.unidade, descricao="2026")
        self.meta = Meta.objects.create(
            unidade_criadora=self.unidade, criado_por=self.user, titulo="Atividade"
        )
        self.programacao = Programacao.objects.create(unidade=self.unidade, data=date(2026, 11, 2))
        self.client.force_login(self.user)
        session = self.client.session
        session["contexto_atual"] = self.unidade.id
        session.save()

    def registrar(self):
        return self.client.post(
            reverse("descanso:feriados_registrar"),
            data={"cadastro_id": self.cadastro.id, "data": "2026-11-02", "descricao": "Finados"},
            content_type="application/json",
        )

    def atividade(self, cancelada):
        return ProgramacaoItem.objects.create(
            programacao=self.programacao, meta=self.meta, cancelada=cancelada
        )

    def test_permite_dia_sem_atividade(self):
        self.assertEqual(self.registrar().status_code, 200)
        self.assertTrue(Feriado.objects.filter(data=date(2026, 11, 2)).exists())

    @override_settings(CSRF_COOKIE_HTTPONLY=True)
    def test_cadastro_com_token_da_pagina_e_cookie_httponly(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        session = client.session
        session["contexto_atual"] = self.unidade.id
        session.save()
        page = client.get(reverse("descanso:feriados"))
        self.assertEqual(page.status_code, 200)
        token = re.search(r'const csrfToken = "([a-zA-Z0-9]+)";', page.content.decode())
        self.assertIsNotNone(token)
        self.assertTrue(page.cookies["csrftoken"]["httponly"])
        response = client.post(
            reverse("descanso:feriados_registrar"),
            data={"cadastro_id": self.cadastro.id, "data": "2026-11-02", "descricao": "Finados"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token.group(1),
        )
        self.assertEqual(response.status_code, 200)

    def test_permite_atividades_canceladas(self):
        self.atividade(cancelada=True)
        self.atividade(cancelada=True)
        self.assertEqual(self.registrar().status_code, 200)
        self.assertEqual(Feriado.objects.count(), 1)

    def test_expediente_administrativo_nao_bloqueia_feriado(self):
        expediente = Meta.objects.create(
            unidade_criadora=self.unidade, criado_por=self.user,
            titulo="Expediente administrativo",
        )
        ProgramacaoItem.objects.create(programacao=self.programacao, meta=expediente)
        item = self.atividade(cancelada=True)
        with self.settings(META_EXPEDIENTE_ID=expediente.id):
            self.assertEqual(self.registrar().status_code, 200)
            self.assertEqual(Feriado.objects.count(), 1)
            Feriado.objects.all().delete()
            item.cancelada = False
            item.save(update_fields=["cancelada"])
            self.assertEqual(self.registrar().status_code, 400)
            self.assertFalse(Feriado.objects.exists())

    def test_bloqueia_se_restar_atividade_nao_cancelada(self):
        self.atividade(cancelada=True)
        item = self.atividade(cancelada=False)
        self.assertEqual(self.registrar().status_code, 400)
        self.assertFalse(Feriado.objects.exists())
        item.cancelada = True
        item.save(update_fields=["cancelada"])
        self.assertEqual(self.registrar().status_code, 200)

    def test_ignora_atividade_de_outra_unidade_ou_data(self):
        outra = No.objects.create(nome="Outra unidade")
        for unidade, data in [(outra, date(2026, 11, 2)), (self.unidade, date(2026, 11, 3))]:
            programacao = Programacao.objects.create(unidade=unidade, data=data)
            ProgramacaoItem.objects.create(programacao=programacao, meta=self.meta)
        self.assertEqual(self.registrar().status_code, 200)


class DescansosUnidadeContextTests(TestCase):
    def setUp(self):
        self.unidade = No.objects.create(nome="Unidade Descanso")

    def test_ignora_descanso_de_servidor_inativo(self):
        servidor_ativo = Servidor.objects.create(
            unidade=self.unidade,
            nome="Servidor Ativo",
            ativo=True,
        )
        servidor_inativo = Servidor.objects.create(
            unidade=self.unidade,
            nome="ENEDINE DIAS",
            ativo=False,
        )
        descanso_ativo = Descanso.objects.create(
            servidor=servidor_ativo,
            tipo=Descanso.Tipo.FERIAS,
            data_inicio=date(2026, 9, 10),
            data_fim=date(2026, 9, 20),
        )
        Descanso.objects.create(
            servidor=servidor_inativo,
            tipo=Descanso.Tipo.FERIAS,
            data_inicio=date(2026, 9, 14),
            data_fim=date(2026, 10, 3),
        )

        context = _build_descansos_unidade_context(
            unidade_id=self.unidade.id,
            hoje=date(2026, 9, 3),
            ano=2026,
        )

        self.assertEqual(context["descansos"], [descanso_ativo])
        self.assertEqual(context["total_descansos"], 1)
        setembro = next(item for item in context["month_filters"] if item["key"] == "2026-09")
        outubro = next(item for item in context["month_filters"] if item["key"] == "2026-10")
        self.assertEqual(setembro["count"], 1)
        self.assertEqual(outubro["count"], 0)


class RelatorioMapaDescansoTests(TestCase):
    def setUp(self):
        self.unidade = No.objects.create(nome="Unidade Mapa")
        self.user = get_user_model().objects.create_user(username="mapa_descanso", password="123456")
        self.client.force_login(self.user)
        session = self.client.session
        session["contexto_atual"] = self.unidade.id
        session.save()

    def test_relatorio_mapa_anual_mantem_doze_meses(self):
        response = self.client.get(reverse("descanso:relatorio_mapa"), {"ano": "2026"})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["periodo_customizado"])
        self.assertEqual(response.context["titulo_periodo"], "2026")
        self.assertEqual(len(response.context["meses_data"]), 12)

    def test_relatorio_mapa_por_periodo_recorta_dias_e_descansos(self):
        servidor = Servidor.objects.create(
            unidade=self.unidade,
            nome="Servidor Periodo",
            ativo=True,
        )
        Descanso.objects.create(
            servidor=servidor,
            tipo=Descanso.Tipo.FERIAS,
            data_inicio=date(2026, 9, 10),
            data_fim=date(2026, 9, 20),
        )

        response = self.client.get(
            reverse("descanso:relatorio_mapa"),
            {"inicio": "2026-09-12", "fim": "2026-09-15"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["periodo_customizado"])
        self.assertEqual(response.context["titulo_periodo"], "12/09/2026 a 15/09/2026")
        self.assertEqual(len(response.context["meses_data"]), 1)
        _, mes_nome, rows = response.context["meses_data"][0]
        self.assertEqual(mes_nome, "Setembro")
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0]["dias"],
            [
                {"numero": 12, "marcado": True},
                {"numero": 13, "marcado": True},
                {"numero": 14, "marcado": True},
                {"numero": 15, "marcado": True},
            ],
        )
