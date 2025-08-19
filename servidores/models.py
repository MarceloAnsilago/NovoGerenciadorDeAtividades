# servidores/models.py
from django.db import models

class Servidor(models.Model):
    unidade = models.ForeignKey("core.No", on_delete=models.CASCADE, related_name="servidores")
    nome = models.CharField(max_length=255)
    telefone = models.CharField(max_length=20, blank=True)
    matricula = models.CharField(max_length=50, blank=True, null=True)
    ativo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nome"]

    def __str__(self):
        return self.nome
