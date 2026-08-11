from django.urls import path

from . import views

app_name = "relatorios"

urlpatterns = [
    path("", views.relatorios_home_view, name="home"),
    path("programacao/", views.relatorio_programacao_view, name="programacao"),
    path("programacao/encerrar-mes/", views.encerrar_programacao_mes, name="programacao_encerrar_mes"),
    path("programacao/reabrir-mes/", views.reabrir_programacao_mes, name="programacao_reabrir_mes"),
]
