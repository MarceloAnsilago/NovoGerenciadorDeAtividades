# programar_atividades/models.py
from django.db import models
from django.conf import settings
from django.utils import timezone


class Programacao(models.Model):
    unidade = models.ForeignKey(
        'core.No', on_delete=models.PROTECT, related_name='programacoes'
    )
    data = models.DateField()

    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='programacoes_criadas'
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    # extras
    observacao = models.TextField(blank=True)
    concluida = models.BooleanField(default=False)
    concluida_em = models.DateTimeField(null=True, blank=True)
    concluida_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.PROTECT, related_name='programacoes_concluidas'
    )

    class Meta:
        ordering = ['-data', '-criado_em']
        constraints = [
            models.UniqueConstraint(
                fields=['unidade', 'data'],
                name='uniq_programacao_unidade_data',
            )
        ]

    def __str__(self):
        return f'{self.unidade} em {self.data:%d/%m/%Y}'

    def marcar_concluida(self, por_usuario=None, valor=True):
        self.concluida = bool(valor)
        if self.concluida:
            self.concluida_em = timezone.now()
            self.concluida_por = por_usuario
        else:
            self.concluida_em = None
            self.concluida_por = None


class ProgramacaoItem(models.Model):
    programacao = models.ForeignKey(
        Programacao, on_delete=models.CASCADE, related_name='itens'
    )
    meta = models.ForeignKey(
        'metas.Meta', on_delete=models.PROTECT, related_name='itens_programados'
    )

    # ajuste o app_label se seu Veiculo estiver em outro app
    veiculo = models.ForeignKey(
        'veiculos.Veiculo', null=True, blank=True, on_delete=models.SET_NULL
    )

    observacao = models.TextField(blank=True)
    concluido = models.BooleanField(default=False)
    concluido_em = models.DateTimeField(null=True, blank=True)
    concluido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.PROTECT, related_name='itens_programados_concluidos'
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['programacao_id', 'id']

    def __str__(self):
        return f'{self.programacao} • {getattr(self.meta, "display_titulo", self.meta)}'

    def marcar_concluido(self, por_usuario=None, valor=True):
        self.concluido = bool(valor)
        if self.concluido:
            self.concluido_em = timezone.now()
            self.concluido_por = por_usuario
        else:
            self.concluido_em = None
            self.concluido_por = None


class ProgramacaoItemServidor(models.Model):
    item = models.ForeignKey(
        ProgramacaoItem, on_delete=models.CASCADE, related_name='servidores'
    )
    servidor = models.ForeignKey('servidores.Servidor', on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['item', 'servidor'], name='uniq_item_servidor'
            )
        ]
        indexes = [models.Index(fields=['item'])]

    def __str__(self):
        return f'{self.item} - {self.servidor}'
