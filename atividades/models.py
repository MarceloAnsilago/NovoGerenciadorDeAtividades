# atividades/models.py
from django.conf import settings
from django.db import models
from django.db.models import Q
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

    code = models.CharField(max_length=50)
    nome = models.CharField(max_length=120)
    descricao = models.TextField(blank=True)
    unidade = models.ForeignKey(
        Unidade,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="areas_atividade",
    )
    ativo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "Área"
        verbose_name_plural = "Áreas"
        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=Q(unidade__isnull=True),
                name="area_unique_global_code",
            ),
            models.UniqueConstraint(
                fields=["code", "unidade"],
                condition=Q(unidade__isnull=False),
                name="area_unique_code_unidade",
            ),
        ]

    def __str__(self):
        return self.nome

    @classmethod
    def build_code(cls, nome):
        raw = slugify(nome or "")
        return raw.upper().replace("-", "_") or (nome or "").upper().replace(" ", "_")

    @classmethod
    def default_codes(cls):
        return [code for code, _ in cls.DEFAULT_AREAS]

    @classmethod
    def visible_to_unidade(cls, unidade, active_only=False):
        filters = Q(unidade__isnull=True, code__in=cls.default_codes())
        if unidade is not None:
            filters |= Q(unidade=unidade)
        qs = cls.objects.filter(filters)
        if active_only:
            qs = qs.filter(ativo=True)
        return qs.order_by("nome")

    @property
    def is_global_default(self):
        return self.unidade_id is None and self.code in self.default_codes()

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self.build_code(self.nome)
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
