from django.db import models
from django.conf import settings

class Plantao(models.Model):
    nome = models.CharField(max_length=120, blank=True)  # opcional: "2025-07-26 a 2025-10-17"
    inicio = models.DateField()
    fim = models.DateField()
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    observacao = models.TextField(blank=True)

    class Meta:
        ordering = ["-inicio"]
        verbose_name = "Plantão"
        verbose_name_plural = "Plantoes"

    def __str__(self):
        return self.nome or f"Plantão {self.inicio} → {self.fim}"


class Semana(models.Model):
    plantao = models.ForeignKey(Plantao, related_name="semanas", on_delete=models.CASCADE)
    inicio = models.DateField()
    fim = models.DateField()
    ordem = models.IntegerField(default=0)  # posição/ordem do grupo

    class Meta:
        ordering = ["ordem", "inicio"]
        verbose_name = "Semana de Plantão"
        verbose_name_plural = "Semanas de Plantão"

    def __str__(self):
        return f"{self.plantao} — {self.inicio} a {self.fim}"


class SemanaServidor(models.Model):
    semana = models.ForeignKey(Semana, related_name="itens", on_delete=models.CASCADE)
    servidor = models.ForeignKey("servidores.Servidor", on_delete=models.CASCADE)  # ajuste app_label se necessário
    ordem = models.IntegerField(default=0)  # ordem dentro da semana (para reproduzir select order)
    telefone_snapshot = models.CharField(max_length=60, blank=True)  # grava o telefone do servidor na hora
    info = models.CharField(max_length=200, blank=True)  # campo livre (ex: observacao)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["semana__ordem", "ordem"]
        verbose_name = "Servidor na Semana"
        verbose_name_plural = "Servidores nas Semanas"

    def __str__(self):
        return f"{self.servidor} @ {self.semana}"
