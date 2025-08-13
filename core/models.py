from django.db import models
from django.conf import settings


class No(models.Model):
    nome = models.CharField(max_length=100)
    tipo = models.CharField(max_length=50)  # AGORA É LIVRE
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='filhos')

    def __str__(self):
        return self.nome
class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    must_change_password = models.BooleanField(default=True)
    no = models.ForeignKey(
        "core.No",  # evita import circular
        null=True, blank=True,
        on_delete=models.SET_NULL,
        help_text="Nó ao qual o usuário está vinculado",
    )

    def __str__(self):
        return f"Perfil de {self.user.get_username()}"