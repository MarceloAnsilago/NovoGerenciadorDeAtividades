from django.db import models
from django.conf import settings
from django.utils import timezone

# Mapeando tabelas existentes (managed=False).
# Evitamos colisão de reverses com related_name='+'.

class Programacao(models.Model):
    data = models.DateField()
    criado_em = models.DateTimeField(default=timezone.now)
    observacao = models.TextField(default="", blank=True)
    concluida = models.BooleanField(default=False)
    concluida_em = models.DateTimeField(null=True, blank=True)

    concluida_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='+',   # 👈 evita colisão com programar_atividades.Programacao.criado_por
    )
    unidade = models.ForeignKey(
        "core.No",
        on_delete=models.PROTECT,
        related_name='+',   # 👈 evita colisão com programar_atividades.Programacao.unidade
    )

    class Meta:
        db_table = "programar_atividades_programacao"
        managed = False
        indexes = [
            models.Index(fields=["data"]),
            models.Index(fields=["unidade"]),
            models.Index(fields=["data", "unidade"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["data", "unidade"], name="uq_prog_data_unidade"),
        ]

    def __str__(self):
        return f"Programação {self.data} (unidade={self.unidade_id})"


class ProgramacaoItem(models.Model):
    observacao = models.TextField(default="", blank=True)
    concluido = models.BooleanField(default=False)
    concluido_em = models.DateTimeField(null=True, blank=True)
    nao_realizada_justificada = models.BooleanField(default=False)
    remarcado_de = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    criado_em = models.DateTimeField(default=timezone.now)

    concluido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    meta = models.ForeignKey(
        "metas.Meta",
        on_delete=models.PROTECT,
        related_name='+',   # 👈 evita colisões
    )
    programacao = models.ForeignKey(
        Programacao,
        on_delete=models.CASCADE,
        related_name='+',   # 👈 evita colisão com reverses do outro app (ex: prog.itens)
    )
    veiculo = models.ForeignKey(
        "veiculos.Veiculo",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )

    class Meta:
        db_table = "programar_atividades_programacaoitem"
        managed = False
        indexes = [
            models.Index(fields=["meta"]),
            models.Index(fields=["programacao", "meta"]),
            models.Index(fields=["remarcado_de"]),
        ]

    def __str__(self):
        return f"Item #{self.pk} (prog={self.programacao_id}, meta={self.meta_id})"

    @property
    def servidores_ids(self):
        return list(self.servidores_links.values_list("servidor_id", flat=True))


class ProgramacaoItemServidor(models.Model):
    item = models.ForeignKey(
        ProgramacaoItem,
        on_delete=models.CASCADE,
        related_name='+',   # 👈 sem reverse no Item deste app
    )
    servidor = models.ForeignKey(
        "servidores.Servidor",
        on_delete=models.PROTECT,
        related_name='+',   # 👈 sem reverse em Servidor deste app
    )

    class Meta:
        db_table = "programar_atividades_programacaoitemservidor"
        managed = False
        indexes = [
            models.Index(fields=["servidor"]),
            models.Index(fields=["item", "servidor"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["item", "servidor"], name="uq_prog_item_servidor"),
        ]

    def __str__(self):
        return f"ItemServidor(item={self.item_id}, servidor={self.servidor_id})"
