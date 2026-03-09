from django.conf import settings
from django.db import models


class ProgramacaoHistorico(models.Model):
    EVENTO_ATIVIDADE_CRIADA = "atividade_criada"
    EVENTO_ATIVIDADE_REMOVIDA = "atividade_removida"
    EVENTO_META_ALTERADA = "meta_alterada"
    EVENTO_OBSERVACAO_ALTERADA = "observacao_alterada"
    EVENTO_SERVIDOR_ADICIONADO = "servidor_adicionado"
    EVENTO_SERVIDOR_REMOVIDO = "servidor_removido"
    EVENTO_VEICULO_ALTERADO = "veiculo_alterado"
    EVENTO_STATUS_ALTERADO = "status_alterado"
    EVENTO_PROGRAMACAO_EXCLUIDA = "programacao_excluida"

    EVENTO_CHOICES = [
        (EVENTO_ATIVIDADE_CRIADA, "Atividade criada"),
        (EVENTO_ATIVIDADE_REMOVIDA, "Atividade removida"),
        (EVENTO_META_ALTERADA, "Meta alterada"),
        (EVENTO_OBSERVACAO_ALTERADA, "Observacao alterada"),
        (EVENTO_SERVIDOR_ADICIONADO, "Servidor adicionado"),
        (EVENTO_SERVIDOR_REMOVIDO, "Servidor removido"),
        (EVENTO_VEICULO_ALTERADO, "Veiculo alterado"),
        (EVENTO_STATUS_ALTERADO, "Status alterado"),
        (EVENTO_PROGRAMACAO_EXCLUIDA, "Programacao excluida"),
    ]

    unidade = models.ForeignKey(
        "core.No",
        on_delete=models.PROTECT,
        related_name="historico_programacao",
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="historico_programacao",
    )
    meta = models.ForeignKey(
        "metas.Meta",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="historico_programacao",
    )
    data_programacao = models.DateField()
    programacao_id = models.PositiveIntegerField(null=True, blank=True)
    item_id = models.PositiveIntegerField(null=True, blank=True)
    evento = models.CharField(max_length=40, choices=EVENTO_CHOICES)
    origem = models.CharField(max_length=30, blank=True, default="")
    titulo_item = models.CharField(max_length=255, blank=True, default="")
    descricao = models.TextField(blank=True, default="")
    status_antes = models.CharField(max_length=40, blank=True, default="")
    status_depois = models.CharField(max_length=40, blank=True, default="")
    detalhes = models.JSONField(default=dict, blank=True)
    snapshot_antes = models.JSONField(default=dict, blank=True)
    snapshot_depois = models.JSONField(default=dict, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em", "-id"]
        indexes = [
            models.Index(fields=["unidade", "data_programacao"]),
            models.Index(fields=["item_id", "criado_em"]),
            models.Index(fields=["evento", "criado_em"]),
        ]
        verbose_name = "Historico da programacao"
        verbose_name_plural = "Historicos da programacao"

    def __str__(self) -> str:
        base = self.titulo_item or f"Item #{self.item_id or '-'}"
        return f"{self.get_evento_display()} - {base}"

