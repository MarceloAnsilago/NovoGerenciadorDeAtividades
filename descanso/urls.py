# descanso/urls.py
from django.urls import path
from . import views

app_name = "descanso"

urlpatterns = [
    path("", views.lista_servidores, name="lista_servidores"),
    path("feriados/", views.feriados, name="feriados"),
    path("feriados/feed/", views.feriados_feed, name="feriados_feed"),
    path("feriados/cadastros/", views.feriados_cadastros, name="feriados_cadastros"),
    path("feriados/cadastro/novo/", views.feriados_cadastro_novo, name="feriados_cadastro_novo"),
    path("feriados/cadastro/excluir/<int:cadastro_id>/", views.feriados_cadastro_excluir, name="feriados_cadastro_excluir"),
    path("feriados/relatorio/mapa/", views.feriados_relatorio_mapa, name="feriados_relatorio_mapa"),
    path("feriados/registrar/", views.feriados_registrar, name="feriados_registrar"),
    path("feriados/excluir/", views.feriados_excluir, name="feriados_excluir"),
    path("novo/", views.criar_descanso, name="criar_descanso"),
    path("todos/", views.descansos_unidade, name="descansos_unidade"),
    path("servidor/<int:servidor_id>/", views.descansos_servidor, name="descansos_servidor"),
    path("editar/<int:pk>/", views.editar_descanso, name="editar_descanso"),
    path("excluir/<int:pk>/", views.excluir_descanso, name="excluir_descanso"),
    path("relatorio/mapa/", views.relatorio_mapa, name="relatorio_mapa"),
]
