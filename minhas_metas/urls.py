# minhas_metas/urls.py
from django.urls import path
from . import views

app_name = "minhas_metas"

urlpatterns = [
    path("", views.minhas_metas_view, name="lista"),
    path("andamento/", views.andamento_atividades_view, name="andamento"),
    path("mapa-atividades/", views.mapa_atividades_view, name="mapa-atividades"),
    path("nao-realizadas/", views.nao_realizadas_view, name="nao-realizadas"),
    path("", views.minhas_metas_view, name="minhas_metas"),  # alias p/ {% url 'minhas_metas' %}
]
