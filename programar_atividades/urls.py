from django.urls import path
from . import views

app_name = "programar_atividades"

urlpatterns = [
    path("", views.calendar_view, name="calendar"),
    path("events/", views.events_feed, name="events_feed"),
    path("metas/", views.metas_disponiveis, name="metas_disponiveis"),
    path("ajax/servidores/", views.servidores_para_data, name="servidores_para_data"),
    path("programacao/", views.programacao_do_dia, name="programacao_do_dia"),
    path("salvar/", views.salvar_programacao, name="salvar_programacao"),
    path("atualizar-programacao/", views.atualizar_programacao, name="atualizar_programacao"),
    path("atualizar-item/", views.atualizar_item, name="atualizar_item"),
    path("excluir-programacao/", views.excluir_programacao, name="excluir_programacao"),
]