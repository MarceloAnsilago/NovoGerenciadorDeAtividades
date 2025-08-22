from django.db import models
# metas/models.py
from django.db import models
from django.db.models import Sum, CheckConstraint, Q, F
from django.utils import timezone
from core.models import No as Unidade
from django.conf import settings
User = settings.AUTH_USER_MODEL

class Atividade(models.Model):
    """
    Catálogo/Tipo de atividade (opcional, mas útil para reuso).
    A MESMA atividade pode aparecer em várias metas/unidades.
    """
    nome = models.CharField(max_length=255, unique=True)
    descricao = models.TextField(blank=True)

    class Meta:
        verbose_name = "Atividade"
        verbose_name_plural = "Atividades"

    def __str__(self):
        return self.nome


class Meta(models.Model):
    """
    A 'meta' é o objetivo-mãe (ex.: 'Vacinar 1.000 bovinos até 30/09').
    Ela nasce em uma unidade (criadora/dona), define prazo e,
    OPCIONALMENTE, a atividade de referência.
    A distribuição para unidades acontece em MetaAlocacao.
    """
    unidade_criadora = models.ForeignKey(
        Unidade, on_delete=models.PROTECT, related_name="metas_criadas"
    )
    atividade = models.ForeignKey(
        Atividade, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="metas"
    )
    titulo = models.CharField(max_length=255)
    descricao = models.TextField(blank=True)
    quantidade_alvo = models.PositiveIntegerField(default=0)
    data_limite = models.DateField(null=True, blank=True)
    criado_por = models.ForeignKey(User, on_delete=models.PROTECT, related_name="metas_criadas_por")
    criado_em = models.DateTimeField(auto_now_add=True)
    # status derivado por propriedades; 'concluida' pode ser útil para "fechar" a meta manualmente
    encerrada = models.BooleanField(default=False)

    class Meta:
        ordering = ["-criado_em"]
        indexes = [
            models.Index(fields=["data_limite"]),
            models.Index(fields=["unidade_criadora"]),
        ]

    def __str__(self):
        return self.titulo

    # ---- Agregações úteis ----
    @property
    def alocado_total(self) -> int:
        return self.alocacoes.aggregate(total=Sum("quantidade_alocada"))["total"] or 0

    @property
    def realizado_total(self) -> int:
        return (
            ProgressoMeta.objects.filter(alocacao__meta=self)
            .aggregate(total=Sum("quantidade"))["total"] or 0
        )

    @property
    def percentual_execucao(self) -> float:
        alvo = self.quantidade_alvo or 0
        if alvo == 0:
            return 0.0
        return min(100.0, (self.realizado_total / alvo) * 100.0)

    @property
    def atrasada(self) -> bool:
        return bool(self.data_limite and timezone.localdate() > self.data_limite and not self.concluida)

    @property
    def concluida(self) -> bool:
        """Concluída quando realizado_total >= quantidade_alvo ou quando encerrada manualmente."""
        return self.encerrada or (self.quantidade_alvo and self.realizado_total >= self.quantidade_alvo)


class MetaAlocacao(models.Model):
    """
    Uma 'alocação' representa a atribuição de parte (ou todo) da meta a uma unidade específica.
    Suporta redistribuição em cadeia via parent (ex.: gerente -> supervisão -> unidade).
    """
    meta = models.ForeignKey(Meta, on_delete=models.CASCADE, related_name="alocacoes")
    unidade = models.ForeignKey(Unidade, on_delete=models.PROTECT, related_name="metas_recebidas")
    quantidade_alocada = models.PositiveIntegerField()
    # Para redistribuição hierárquica (cadeia de responsabilidade)
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="redistribuicoes"
    )
    atribuida_por = models.ForeignKey(User, on_delete=models.PROTECT, related_name="atribuicoes_feitas")
    atribuida_em = models.DateTimeField(auto_now_add=True)
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        unique_together = [("meta", "unidade", "parent")]  # evita duplicidade na mesma ramificação
        indexes = [
            models.Index(fields=["meta", "unidade"]),
        ]

    def __str__(self):
        return f"{self.meta.titulo} -> {self.unidade.nome} ({self.quantidade_alocada})"

    @property
    def realizado(self) -> int:
        return self.progresso.aggregate(total=Sum("quantidade"))["total"] or 0

    @property
    def saldo(self) -> int:
        return max(0, (self.quantidade_alocada or 0) - self.realizado)

    @property
    def percentual_execucao(self) -> float:
        alvo = self.quantidade_alocada or 0
        if alvo == 0:
            return 0.0
        return min(100.0, (self.realizado / alvo) * 100.0)


class ProgressoMeta(models.Model):
    """
    Lançamentos de execução realizados pela unidade alocada (movimentação diária/por demanda).
    Ex.: hoje concluímos 7 doses; amanhã mais 3; etc.
    """
    alocacao = models.ForeignKey(MetaAlocacao, on_delete=models.CASCADE, related_name="progresso")
    data = models.DateField(default=timezone.localdate)
    quantidade = models.PositiveIntegerField()
    registrado_por = models.ForeignKey(User, on_delete=models.PROTECT, related_name="progresso_registrado")
    criado_em = models.DateTimeField(auto_now_add=True)
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-data", "-criado_em"]
        indexes = [
            models.Index(fields=["data"]),
            models.Index(fields=["alocacao"]),
        ]
        # Evita lançamentos negativos e garante datas válidas
        constraints = [
            CheckConstraint(check=Q(quantidade__gt=0), name="progresso_quantidade_gt_0"),
        ]

    def __str__(self):
        return f"{self.alocacao.unidade.nome} +{self.quantidade} em {self.data}"
