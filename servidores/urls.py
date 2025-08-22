from django.urls import path
from . import views

app_name = "servidores"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("<int:pk>/editar/", views.editar, name="editar"),

    # mantém toggle caso queira usá-lo
    path("<int:pk>/toggle-ativo/", views.toggle_ativo, name="toggle_ativo"),

    # rotas separadas (compatibilidade com templates antigos)
    path("<int:pk>/inativar/", views.inativar, name="inativar"),
    path("<int:pk>/ativar/", views.ativar, name="ativar"),

    # exclusão (opcional)
    path("<int:pk>/excluir/", views.excluir, name="excluir"),
]