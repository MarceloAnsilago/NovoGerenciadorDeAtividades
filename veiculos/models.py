from django.db import models
from core.models import No 

class Veiculo(models.Model):
    unidade = models.ForeignKey(No, on_delete=models.CASCADE, related_name='veiculos')
    nome = models.CharField(max_length=100)
    placa = models.CharField(max_length=10, unique=True)
    ativo = models.BooleanField(default=True)

    def __str__(self):
        return f'{self.nome} ({self.placa})'
