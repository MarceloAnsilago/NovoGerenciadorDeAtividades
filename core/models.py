from django.db import models

class No(models.Model):
    nome = models.CharField(max_length=100)
    tipo = models.CharField(max_length=50)  # AGORA É LIVRE
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='filhos')

    def __str__(self):
        return self.nome
