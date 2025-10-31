from django.db import models
from django.contrib.auth.models import User

from .utils import gerar_senha_provisoria as gerar_token


class No(models.Model):
    TIPO_CHOICES = (
        ('setor', 'Setor'),
        ('departamento', 'Departamento'),
        ('outro', 'Outro'),
    )

    nome = models.CharField(max_length=255)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='outro')
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='filhos')

    def __str__(self):
        return self.nome

    def to_jstree(self):
        return {
            'id': self.id,
            'parent': '#' if self.parent is None else self.parent.id,
            'text': self.nome,
        }

    class Meta:
        permissions = [
            ("assumir_unidade", "Pode assumir unidades"),
        ]


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    unidade = models.ForeignKey(No, on_delete=models.CASCADE)

    senha_provisoria = models.CharField(
        max_length=100, blank=True, null=True,
        help_text="Token de ativação para primeiro acesso"
    )
    ativado = models.BooleanField(
        default=False,
        help_text="Se o usuário já concluiu o primeiro acesso"
    )

    def __str__(self):
        return f"{self.user.username} ({self.unidade.nome})"

    def gerar_senha_provisoria(self, tamanho=10):
        self.senha_provisoria = gerar_token(tamanho)
        self.ativado = False
        self.save()
        return self.senha_provisoria


class Policy(models.Model):
    user_profile = models.OneToOneField(UserProfile, on_delete=models.CASCADE, related_name='policy')

    can_read = models.BooleanField(default=True)
    can_write = models.BooleanField(default=False)

    SCOPE_CHOICES = [
        ('GLOBAL', 'Global'),
        ('LOCAL', 'Local'),
        ('RESTRICTED', 'Restricted'),
    ]
    scope = models.CharField(max_length=20, choices=SCOPE_CHOICES, default='RESTRICTED')

    def __str__(self):
        return f"Policy for {self.user_profile.user.username}"
