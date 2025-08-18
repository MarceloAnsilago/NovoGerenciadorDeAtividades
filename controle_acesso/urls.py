from django.urls import path
from . import views

app_name = "controle_acesso"

urlpatterns = [
    path("gerenciar/", views.gerenciar_permissoes, name="gerenciar_permissoes"),
    path("grupo/<int:grupo_id>/", views.editar_grupo, name="editar_grupo"),
]