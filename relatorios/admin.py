from django.contrib import admin

from .models import ProgramacaoHistorico


@admin.register(ProgramacaoHistorico)
class ProgramacaoHistoricoAdmin(admin.ModelAdmin):
    list_display = (
        "criado_em",
        "data_programacao",
        "evento",
        "titulo_item",
        "usuario",
        "unidade",
    )
    list_filter = ("evento", "data_programacao", "unidade")
    search_fields = ("titulo_item", "descricao", "item_id", "programacao_id")
    readonly_fields = (
        "unidade",
        "usuario",
        "meta",
        "data_programacao",
        "programacao_id",
        "item_id",
        "evento",
        "origem",
        "titulo_item",
        "descricao",
        "status_antes",
        "status_depois",
        "detalhes",
        "snapshot_antes",
        "snapshot_depois",
        "criado_em",
    )

