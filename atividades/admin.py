from django.contrib import admin
from .models import Atividade

@admin.register(Atividade)
class AtividadeAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'area', 'unidade_origem', 'ativo', 'criado_em')
    list_filter = ('area', 'ativo', 'unidade_origem')
    search_fields = ('titulo', 'descricao')