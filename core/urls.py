# core/urls.py
from django.urls import path
from . import views

app_name = "core"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("estrutura/", views.admin_arvore, name="admin_arvore"),
    path("perfis/", views.perfis, name="perfis"),
    path("perfis/criar/", views.criar_perfil, name="criar_perfil"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),

    # CRUD do jsTree
    path("nos/", views.nos_list, name="nos_list"),
    path("nos/criar/", views.nos_criar, name="nos_criar"),
    path("nos/renomear/<int:pk>/", views.nos_renomear, name="nos_renomear"),
    path("nos/mover/<int:pk>/", views.nos_mover, name="nos_mover"),
    path("nos/deletar/<int:pk>/", views.nos_deletar, name="nos_deletar"),

    # Primeiro acesso
    path("primeiro-acesso/", views.primeiro_acesso_token_view, name="primeiro_acesso_token"),
    path("primeiro-acesso/trocar/", views.trocar_senha_primeiro_acesso, name="trocar_senha_primeiro_acesso"),

    # assumir unidade (note o nome do parâmetro: unidade_id)
    path("assumir-unidade/<int:unidade_id>/", views.assumir_unidade, name="assumir_unidade"),

    path("voltar-contexto/", views.voltar_contexto, name="voltar_contexto"),

    path("perfis/<int:user_id>/excluir/", views.excluir_perfil, name="excluir_perfil"),
    path("perfis/<int:user_id>/redefinir-senha/", views.redefinir_senha, name="redefinir_senha"),
]
