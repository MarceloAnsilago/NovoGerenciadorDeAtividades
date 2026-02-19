# metas/models.py
from django.conf import settings
from django.db import models
from django.db.models import Sum, Q, CheckConstraint
from django.utils import timezone

# usar o valor de AUTH_USER_MODEL (string) é ok ao passar para ForeignKey
User = settings.AUTH_USER_MODEL

from core.models import No as Unidade  # assume que core está correto e importável


class Meta(models.Model):
    unidade_criadora = models.ForeignKey(
        Unidade, on_delete=models.PROTECT, related_name="metas_criadas"
    )
    atividade = models.ForeignKey(
        "atividades.Atividade",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="metas"
    )
    titulo = models.CharField(max_length=255)
    descricao = models.TextField(blank=True)
    quantidade_alvo = models.PositiveIntegerField(default=0)
    data_inicio = models.DateField(null=True, blank=True)
    data_limite = models.DateField(null=True, blank=True)
    criado_por = models.ForeignKey(User, on_delete=models.PROTECT, related_name="metas_criadas_por")
    criado_em = models.DateTimeField(auto_now_add=True)
    encerrada = models.BooleanField(default=False)

    class Meta:
        ordering = ["-criado_em"]
        indexes = [
            models.Index(fields=["data_inicio"]),
            models.Index(fields=["data_limite"]),
            models.Index(fields=["unidade_criadora"]),
        ]
        verbose_name = "Meta"
        verbose_name_plural = "Metas"

    def __str__(self):
        return self.display_titulo

    @property
    def display_titulo(self):
        t = self.titulo
        if t and str(t).strip():
            return str(t).strip()
        atividade = getattr(self, "atividade", None)
        if atividade:
            return getattr(atividade, "titulo", None) or getattr(atividade, "nome", None) or "(sem título)"
        return "(sem título)"

    def save(self, *args, **kwargs):
        # normaliza título e tenta preencher a partir da atividade se estiver vazio
        if self.titulo is not None:
            self.titulo = str(self.titulo).strip()
        if not self.titulo:
            atividade = getattr(self, "atividade", None)
            if atividade:
                possible = getattr(atividade, "titulo", None) or getattr(atividade, "nome", None)
                if possible:
                    self.titulo = str(possible).strip()
        super().save(*args, **kwargs)

    @property
    def alocado_total(self) -> int:
        return self.alocacoes.aggregate(total=Sum("quantidade_alocada"))["total"] or 0

    @property
    def realizado_total(self) -> int:
        """
        Soma todo o progresso ligado às alocações desta meta de forma segura:
        - tenta agregação direta via related lookups;
        - em caso de erro (cenários raros) faz fallback iterativo.
        """
        try:
            total = self.alocacoes.aggregate(total=Sum("progresso__quantidade"))["total"]
            return total or 0
        except Exception:
            # fallback mais robusto
            try:
                total = 0
                for al in self.alocacoes.all():
                    t = al.progresso.aggregate(total=Sum("quantidade"))["total"] or 0
                    total += t
                return total
            except Exception:
                return 0

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
        return self.encerrada or (self.quantidade_alvo and self.realizado_total >= self.quantidade_alvo)


class MetaAlocacao(models.Model):
    meta = models.ForeignKey(Meta, on_delete=models.CASCADE, related_name="alocacoes")
    unidade = models.ForeignKey(Unidade, on_delete=models.PROTECT, related_name="metas_recebidas")
    quantidade_alocada = models.PositiveIntegerField()
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="redistribuicoes"
    )
    atribuida_por = models.ForeignKey(User, on_delete=models.PROTECT, related_name="atribuicoes_feitas")
    atribuida_em = models.DateTimeField(auto_now_add=True)
    observacao = models.CharField(max_length=255, blank=True)

    class Meta:
        unique_together = [("meta", "unidade", "parent")]
        indexes = [
            models.Index(fields=["meta", "unidade"]),
        ]
        verbose_name = "Alocação de Meta"
        verbose_name_plural = "Alocações de Metas"

    def __str__(self):
        # tolerante se meta.titulo vazio
        titulo = getattr(self.meta, "display_titulo", getattr(self.meta, "titulo", "(sem título)"))
        return f"{titulo} -> {self.unidade.nome} ({self.quantidade_alocada})"

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
        constraints = [
            CheckConstraint(check=Q(quantidade__gt=0), name="progresso_quantidade_gt_0"),
        ]
        verbose_name = "Progresso de Meta"
        verbose_name_plural = "Progresso de Metas"

    def __str__(self):
        unidade_nome = getattr(self.alocacao, "unidade", None)
        return f"{unidade_nome.nome if unidade_nome else '—'} +{self.quantidade} em {self.data}"
