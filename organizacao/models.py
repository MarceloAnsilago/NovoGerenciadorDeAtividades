from django.db import models
from django.contrib.auth.models import User, Permission

class Unidade(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    parent = models.ForeignKey("self", null=True, blank=True,
                               on_delete=models.SET_NULL, related_name="filhas")
    status = models.CharField(max_length=20, default="Ativo")
    class Meta: ordering = ["nome"]
    def __str__(self): return self.nome

class PerfilPolitica(models.Model):
    nome = models.CharField(max_length=60, unique=True)
    descricao = models.CharField(max_length=255, blank=True)
    permissoes = models.ManyToManyField(Permission, blank=True)
    class Meta:
        ordering = ["nome"]
        permissions = [("manage_policies", "Pode gerenciar perfis e políticas")]
    def __str__(self): return self.nome

class PerfilUsuario(models.Model):
    ALCANCE = (("self","Apenas esta unidade"), ("subtree","Esta unidade e descendentes"))
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name="vinculos")
    unidade = models.ForeignKey(Unidade, on_delete=models.CASCADE)
    perfil_politica = models.ForeignKey(PerfilPolitica, on_delete=models.PROTECT, null=True, blank=True)
    alcance = models.CharField(max_length=16, choices=ALCANCE, default="self")
    class Meta:
        unique_together = [("usuario","unidade","perfil_politica","alcance")]
        ordering = ["usuario__username","unidade__nome"]
    def __str__(self):
        pol = self.perfil_politica.nome if self.perfil_politica_id else "—"
        return f"{self.usuario.username} @ {self.unidade} [{pol}/{self.alcance}]"


# Create your models here.
