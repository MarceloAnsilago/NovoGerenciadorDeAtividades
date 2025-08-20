# atividades/models.py
from django.conf import settings
from django.db import models
from core.models import No as Unidade

class Atividade(models.Model):
    class Area(models.TextChoices):
        ANIMAL = "ANIMAL", "Animal"
        VEGETAL = "VEGETAL", "Vegetal"
        ANIMAL_VEGETAL = "ANIMAL_VEGETAL", "Animal e Vegetal"  # NOVO
        APOIO  = "APOIO",  "Apoio"
        OUTROS = "OUTROS", "Outros"

    titulo = models.CharField(max_length=200, unique=True)
    descricao = models.TextField(blank=True)

    # aumente para caber "ANIMAL_VEGETAL"
    area = models.CharField(
        max_length=20,                # <- era 10
        choices=Area.choices,
        default=Area.OUTROS,
    )

    unidade_origem = models.ForeignKey(Unidade, on_delete=models.PROTECT, related_name='atividades_origem')
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='atividades_criadas')

    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['titulo']

    def __str__(self):
        return self.titulo
