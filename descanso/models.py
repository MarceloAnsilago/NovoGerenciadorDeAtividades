from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone

# Ajuste o import abaixo para o seu app de servidores
from servidores.models import Servidor
from core.models import No as Unidade


class HistoricalFeriadoIndex(models.Index):
    """Preserva o nome de 31 caracteres de 0002, valido no PostgreSQL.

    O limite de 30 do Index e portabilidade entre bancos. A serializacao
    permanece a de um Index comum, sem introduzir alteracao de schema.
    """

    max_name_length = 31

    def deconstruct(self):
        _, args, kwargs = super().deconstruct()
        return "django.db.models.Index", args, kwargs

    def __eq__(self, other):
        if isinstance(other, models.Index):
            return self.deconstruct() == other.deconstruct()
        return NotImplemented


class Descanso(models.Model):
    class Tipo(models.TextChoices):
        RECESSO = "RECESSO", "Recesso"
        FERIAS = "FERIAS", "Férias"
        LICENCA = "LICENCA", "Licença"
        DIARIAS = "DIARIAS", "Diárias"
        FOLGA_COMP = "FOLGA_COMP", "Folga compensatória"
        FOLGA_ELEITORAL = "FOLGA_ELEITORAL", "Folga eleitoral"
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


class FeriadoCadastro(models.Model):
    # Preserve o AutoField criado pela migracao 0002, apesar do padrao BigAutoField.
    id = models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")
    unidade = models.ForeignKey(Unidade, on_delete=models.CASCADE, related_name="cadastros_feriados")
    descricao = models.CharField(max_length=120)
    criado_em = models.DateTimeField(auto_now_add=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="feriados_cadastros_criados"
    )

    class Meta:
        ordering = ["-criado_em", "-id"]
        indexes = [
            models.Index(fields=["unidade", "descricao"], name="descanso_fe_unidade_6b8f0c_idx"),
        ]

    def __str__(self):
        return f"{self.descricao} ({self.unidade})"


class Feriado(models.Model):
    # Preserve o tipo e os metadados da chave primaria historica (0002).
    id = models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")
    cadastro = models.ForeignKey(FeriadoCadastro, on_delete=models.CASCADE, related_name="feriados")
    data = models.DateField()
    descricao = models.CharField(max_length=120, blank=True, default="")
    criado_em = models.DateTimeField(auto_now_add=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="feriados_criados"
    )

    class Meta:
        ordering = ["data", "id"]
        indexes = [
            HistoricalFeriadoIndex(fields=["cadastro", "data"], name="descanso_fe_cadastro_d3c3aa_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["cadastro", "data"], name="uniq_feriado_cadastro_data")
        ]

    def __str__(self):
        return f"{self.data} - {self.descricao or self.cadastro.descricao}"



