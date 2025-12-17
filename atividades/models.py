# atividades/models.py
from django.conf import settings
from django.db import models
from django.utils.text import slugify

from core.models import No as Unidade


class Area(models.Model):
    CODE_ANIMAL = "ANIMAL"
    CODE_VEGETAL = "VEGETAL"
    CODE_ANIMAL_VEGETAL = "ANIMAL_VEGETAL"
    CODE_APOIO = "APOIO"
    CODE_OUTROS = "OUTROS"

    DEFAULT_AREAS = [
        (CODE_ANIMAL, "Animal"),
        (CODE_VEGETAL, "Vegetal"),
        (CODE_ANIMAL_VEGETAL, "Animal e Vegetal"),
        (CODE_APOIO, "Apoio"),
        (CODE_OUTROS, "Outros"),
    ]

    code = models.CharField(max_length=50, unique=True)
    nome = models.CharField(max_length=120)
    descricao = models.TextField(blank=True)
    ativo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "Área"
        verbose_name_plural = "Áreas"

    def __str__(self):
        return self.nome

    def save(self, *args, **kwargs):
        if not self.code:
            raw = slugify(self.nome or "")
            self.code = raw.upper().replace("-", "_") or self.nome.upper().replace(" ", "_")
        super().save(*args, **kwargs)


class Atividade(models.Model):
    titulo = models.CharField(max_length=200)
    descricao = models.TextField(blank=True)
    area = models.ForeignKey("atividades.Area", on_delete=models.PROTECT, related_name="atividades")

    unidade_origem = models.ForeignKey(Unidade, on_delete=models.PROTECT, related_name="atividades_origem")
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="atividades_criadas")

    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["titulo"]
        constraints = [
            models.UniqueConstraint(fields=["titulo", "unidade_origem"], name="atividade_unique_titulo_unidade")
        ]

    def __str__(self):
        return self.titulo
