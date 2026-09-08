from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import No
from servidores.models import Servidor

from .models import Descanso
from .views import _build_descansos_unidade_context


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
