# descanso/urls.py
from django.urls import path
from . import views

app_name = "descanso"

urlpatterns = [
    path("", views.lista_servidores, name="lista_servidores"),
    path("novo/", views.criar_descanso, name="criar_descanso"),
    path("todos/", views.descansos_unidade, name="descansos_unidade"),
    path("servidor/<int:servidor_id>/", views.descansos_servidor, name="descansos_servidor"),
    path("editar/<int:pk>/", views.editar_descanso, name="editar_descanso"),
    path("excluir/<int:pk>/", views.excluir_descanso, name="excluir_descanso"),
    path("relatorio/mapa/", views.relatorio_mapa, name="relatorio_mapa"),
]