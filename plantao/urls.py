from django.urls import path
from . import views

app_name = "plantao"

urlpatterns = [
    path("lista/", views.lista_plantao, name="lista_plantao"),

]