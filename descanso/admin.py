from django.contrib import admin
from .models import Descanso

@admin.register(Descanso)
class DescansoAdmin(admin.ModelAdmin):
    list_display = ("servidor", "tipo", "data_inicio", "data_fim", "ativo_agora")
    list_filter = ("tipo", "data_inicio", "data_fim")
    search_fields = ("servidor__nome", "observacoes")