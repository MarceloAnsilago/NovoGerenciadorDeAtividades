from django.db import models
from django.conf import settings

class Plantao(models.Model):
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
        return f"Plantão {self.inicio} → {self.fim}"


class SemanaPlantao(models.Model):
    plantao = models.ForeignKey(Plantao, related_name="semanas", on_delete=models.CASCADE)
    # Ajuste aqui se o app que contém o modelo Servidor tiver outro app_label
    servidor = models.ForeignKey('servidores.Servidor', on_delete=models.CASCADE)  # <-- ver observação acima
    dia = models.DateField()
    info = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["dia"]
        verbose_name = "SemanaPlantao"
        verbose_name_plural = "Semanas de Plantão"

    def __str__(self):
        return f"{self.servidor} — {self.dia}"