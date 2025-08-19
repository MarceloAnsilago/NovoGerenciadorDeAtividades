from django.urls import path
from . import views

app_name = "servidores"

urlpatterns = [
    path("", views.lista, name="lista"),                       # página: form + listagem
    path("<int:pk>/editar/", views.editar, name="editar"),     # editar servidor
    path("<int:pk>/ativar/", views.ativar, name="ativar"),     # marcar ativo
    path("<int:pk>/inativar/", views.inativar, name="inativar")# marcar inativo
]