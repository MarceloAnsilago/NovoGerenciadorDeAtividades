from django.urls import path
from . import views

app_name = "controle_acesso"

urlpatterns = [
    # tela de permissões por usuário
    path("gerenciar/", views.gerenciar_permissoes_usuario, name="gerenciar_permissoes"),
    # editor de grupo (se você usa)
    path("grupo/<int:grupo_id>/", views.editar_grupo, name="editar_grupo"),
]