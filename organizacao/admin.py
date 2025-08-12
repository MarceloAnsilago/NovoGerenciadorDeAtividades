from django.contrib import admin
from .models import Unidade, PerfilPolitica, PerfilUsuario

@admin.register(Unidade)
class UnidadeAdmin(admin.ModelAdmin):
    list_display = ("nome", "parent", "status")
    search_fields = ("nome",)

@admin.register(PerfilPolitica)
class PerfilPoliticaAdmin(admin.ModelAdmin):
    list_display = ("nome", "descricao")
    search_fields = ("nome",)
    filter_horizontal = ("permissoes",)

@admin.register(PerfilUsuario)
class PerfilUsuarioAdmin(admin.ModelAdmin):
    list_display = ("usuario", "unidade", "perfil_politica", "alcance")
    list_filter = ("alcance", "perfil_politica")
    search_fields = ("usuario__username", "unidade__nome")
