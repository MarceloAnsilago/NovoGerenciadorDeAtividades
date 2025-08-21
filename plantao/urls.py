from django.urls import path
from . import views

app_name = "plantao"

urlpatterns = [
    path("lista/", views.lista_plantao, name="lista_plantao"),
    path("verificar-descanso/", views.verificar_descanso, name="verificar_descanso"),
]