# programar/urls.py
from django.urls import path
from . import views

app_name = "programar"

urlpatterns = [
    path("", views.calendario_view, name="calendario"),
    # stubs para já deixar a tela futura funcionando sem erro
    path("api/events/", views.events_feed, name="events_feed"),
    path("api/metas/", views.metas_disponiveis, name="metas_disponiveis"),
    path("api/servidores/", views.servidores_para_data, name="servidores_para_data"),
    path("api/salvar/", views.salvar_programacao, name="salvar_programacao"),
    path("api/programacao-dia/", views.programacao_do_dia_orm, name="programacao_do_dia"),
    path("api/excluir/", views.excluir_programacao_secure, name="excluir_programacao"),
    path("api/relatorios/", views.relatorios_parcial, name="relatorios_parcial"),
    path("print/relatorio-semana/", views.print_relatorio_semana, name="print_relatorio_semana"),
    path("api/plantao/servidores-intervalo/", views.servidores_por_intervalo, name="servidores_por_intervalo"),
]
