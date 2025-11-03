from django.contrib import admin

from .models import Cargo, Servidor


@admin.register(Cargo)
class CargoAdmin(admin.ModelAdmin):
    list_display = ("nome", "descricao", "created_at")
    search_fields = ("nome",)
    ordering = ("nome",)


@admin.register(Servidor)
class ServidorAdmin(admin.ModelAdmin):
    list_display = ("nome", "cargo", "unidade", "ativo")
    list_filter = ("ativo", "cargo", "unidade")
    search_fields = ("nome", "matricula", "telefone")
    ordering = ("nome",)
