# atividades/urls.py
from django.urls import path
from . import views

app_name = "atividades"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("<int:pk>/editar/", views.editar, name="editar"),
    path("<int:pk>/toggle-ativo/", views.toggle_ativo, name="toggle_ativo"),
]