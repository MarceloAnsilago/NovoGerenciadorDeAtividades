from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.contrib.auth.models import Permission
from core.models import UserProfile, No

class RedefinirSenhaTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user(username='admin', email='admin@test.com')
        self.admin.set_password('admin123')
        self.admin.save()

        unidade = No.objects.create(nome="Unidade Teste")
        self.profile = UserProfile.objects.create(user=self.admin, unidade=unidade)

        # Permissão necessária
        permission = Permission.objects.get(codename='change_userprofile')
        self.admin.user_permissions.add(permission)

        self.client.login(username='admin', password='admin123')

    def test_redefinir_senha(self):
        url = reverse('core:redefinir_senha', args=[self.admin.id])
        response = self.client.post(url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['username'], self.admin.username)
        self.assertTrue('senha_provisoria' in data)
