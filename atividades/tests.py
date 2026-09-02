from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .forms import AreaForm
from .models import Area
from core.models import No


class AreaFormTests(TestCase):
    def test_rejects_duplicate_generated_code_in_same_unit_scope(self):
        unidade = No.objects.create(nome="SDA")
        Area.objects.create(
            code="APOIO_AOS_PONTOS_FOCAIS_DO_SIGA",
            nome="Apoio aos pontos focais do SIGA",
            unidade=unidade,
        )

        form = AreaForm(
            data={
                "nome": "Apoio aos pontos focais do SIGA",
                "descricao": "",
                "ativo": "on",
            },
            unidade=unidade,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("nome", form.errors)

    def test_allows_same_generated_code_in_different_units(self):
        smg = No.objects.create(nome="SMG")
        sda = No.objects.create(nome="SDA")
        Area.objects.create(
            code="APOIO_AOS_PONTOS_FOCAIS_DO_SIGA",
            nome="Apoio aos pontos focais do SIGA",
            unidade=smg,
        )

        form = AreaForm(
            data={
                "nome": "Apoio aos pontos focais do SIGA",
                "descricao": "",
                "ativo": "on",
            },
            unidade=sda,
        )

        self.assertTrue(form.is_valid())

    def test_sets_generated_code_on_save(self):
        unidade = No.objects.create(nome="SDA")
        form = AreaForm(
            data={
                "nome": "Fiscalizacao local",
                "descricao": "",
                "ativo": "on",
            },
            unidade=unidade,
        )

        self.assertTrue(form.is_valid())
        area = form.save()

        self.assertEqual(area.code, "FISCALIZACAO_LOCAL")
        self.assertEqual(area.unidade, unidade)

    def test_visible_to_unidade_hides_legacy_debug_and_other_unit_areas(self):
        smg = No.objects.create(nome="SMG")
        sda = No.objects.create(nome="SDA")
        Area.objects.get_or_create(code=Area.CODE_APOIO, defaults={"nome": "Apoio"})
        Area.objects.create(code="AREA_DEBUG_AUTO", nome="Area Debug", ativo=False)
        Area.objects.create(code="AREA_SMG", nome="Area SMG", unidade=smg)
        sda_area = Area.objects.create(code="AREA_SDA", nome="Area SDA", unidade=sda)

        visible = list(Area.visible_to_unidade(sda).values_list("code", flat=True))

        self.assertIn(Area.CODE_APOIO, visible)
        self.assertIn(sda_area.code, visible)
        self.assertNotIn("AREA_DEBUG_AUTO", visible)
        self.assertNotIn("AREA_SMG", visible)


class AreaViewsTests(TestCase):
    def setUp(self):
        self.unidade = No.objects.create(nome="SDA")
        self.user = get_user_model().objects.create_user(
            username="areas_user",
            email="areas@example.com",
            password="secret123",
        )
        self.client.force_login(self.user)

    def test_duplicate_area_returns_form_error_instead_of_500(self):
        Area.objects.create(
            code="APOIO_AOS_PONTOS_FOCAIS_DO_SIGA",
            nome="Apoio aos pontos focais do SIGA",
            unidade=self.unidade,
        )
        session = self.client.session
        session["contexto_atual"] = self.unidade.id
        session.save()

        response = self.client.post(
            reverse("atividades:areas_lista"),
            {
                "nome": "Apoio aos pontos focais do SIGA",
                "descricao": "",
                "ativo": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context["form"], "nome", "Já existe uma área cadastrada com este nome.")

    def test_superuser_with_unit_context_sees_only_scoped_areas(self):
        admin = get_user_model().objects.create_superuser(
            username="root_areas",
            email="root_areas@example.com",
            password="secret123",
        )
        smg = No.objects.create(nome="SMG")
        Area.objects.get_or_create(code=Area.CODE_APOIO, defaults={"nome": "Apoio"})
        Area.objects.create(code="AREA_DEBUG_AUTO", nome="Area Debug", ativo=False)
        Area.objects.create(code="AREA_SMG", nome="Area SMG", unidade=smg)
        sda_area = Area.objects.create(code="AREA_SDA", nome="Area SDA", unidade=self.unidade)
        self.client.force_login(admin)
        session = self.client.session
        session["contexto_atual"] = self.unidade.id
        session.save()

        response = self.client.get(reverse("atividades:areas_lista"))
        visible = list(response.context["areas"].values_list("code", flat=True))

        self.assertEqual(response.status_code, 200)
        self.assertIn(Area.CODE_APOIO, visible)
        self.assertIn(sda_area.code, visible)
        self.assertNotIn("AREA_DEBUG_AUTO", visible)
        self.assertNotIn("AREA_SMG", visible)
