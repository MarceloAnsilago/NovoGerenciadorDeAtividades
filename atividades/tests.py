from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .forms import AreaForm
from .models import Area


class AreaFormTests(TestCase):
    def test_rejects_duplicate_generated_code(self):
        Area.objects.create(code="APOIO_AOS_PONTOS_FOCAIS_DO_SIGA", nome="Apoio aos pontos focais do SIGA")

        form = AreaForm(
            data={
                "nome": "Apoio aos pontos focais do SIGA",
                "descricao": "",
                "ativo": "on",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("nome", form.errors)

    def test_sets_generated_code_on_save(self):
        form = AreaForm(
            data={
                "nome": "Fiscalizacao local",
                "descricao": "",
                "ativo": "on",
            }
        )

        self.assertTrue(form.is_valid())
        area = form.save()

        self.assertEqual(area.code, "FISCALIZACAO_LOCAL")


class AreaViewsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="areas_user",
            email="areas@example.com",
            password="secret123",
        )
        self.client.force_login(self.user)

    def test_duplicate_area_returns_form_error_instead_of_500(self):
        Area.objects.create(code="APOIO_AOS_PONTOS_FOCAIS_DO_SIGA", nome="Apoio aos pontos focais do SIGA")

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
