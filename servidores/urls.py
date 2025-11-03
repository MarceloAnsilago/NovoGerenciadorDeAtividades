from django.urls import path

from . import views

app_name = "servidores"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("<int:pk>/editar/", views.editar, name="editar"),
    path("<int:pk>/inativar/", views.inativar, name="inativar"),
    path("<int:pk>/ativar/", views.ativar, name="ativar"),
    path("cargos/", views.cargos_lista, name="cargos_lista"),
    path("cargos/<int:pk>/editar/", views.cargo_editar, name="cargo_editar"),
]
