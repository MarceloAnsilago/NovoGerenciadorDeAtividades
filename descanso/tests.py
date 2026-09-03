from datetime import date

from django.test import TestCase

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
