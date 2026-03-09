from django.urls import path

from . import views

app_name = "relatorios"

urlpatterns = [
    path("", views.relatorios_home_view, name="home"),
    path("programacao/", views.relatorio_programacao_view, name="programacao"),
]
