from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone

# Ajuste o import abaixo para o seu app de servidores
from servidores.models import Servidor


class Descanso(models.Model):
    class Tipo(models.TextChoices):
        FERIAS = "FERIAS", "Férias"
        LICENCA = "LICENCA", "Licença"
        FOLGA_COMP = "FOLGA_COMP", "Folga compensatória"
        AFASTAMENTO = "AFASTAMENTO", "Afastamento"
        ATESTADO = "ATESTADO", "Atestado"

    servidor = models.ForeignKey(Servidor, on_delete=models.CASCADE, related_name="descansos")
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    data_inicio = models.DateField()
    data_fim = models.DateField()
    observacoes = models.TextField(blank=True)

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="descansos_criados"
    )

    class Meta:
        ordering = ["-data_inicio", "-id"]
        indexes = [
            models.Index(fields=["servidor", "data_inicio"]),
            models.Index(fields=["servidor", "data_fim"]),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} - {self.servidor} ({self.data_inicio} a {self.data_fim})"

    def clean(self):
        if self.data_fim < self.data_inicio:
            raise ValidationError("A data final não pode ser anterior à data inicial.")

        # Validação de sobreposição de períodos para o mesmo servidor
        qs = Descanso.objects.filter(servidor=self.servidor)
        if self.pk:
            qs = qs.exclude(pk=self.pk)
        # Sobrepõe quando inicio <= fim_existente e fim >= inicio_existente
        overlap = qs.filter(data_inicio__lte=self.data_fim, data_fim__gte=self.data_inicio).exists()
        if overlap:
            raise ValidationError("Já existe um descanso cadastrado que sobrepõe este período para esse servidor.")

    @property
    def ativo_agora(self) -> bool:
        hoje = timezone.localdate()
        return self.data_inicio <= hoje <= self.data_fim
