import core.views as views
from .views import assumir_unidade
from .views import voltar_contexto
from django.urls import path, include
app_name = "core"
from .views import DashboardView

urlpatterns = [
    path("", DashboardView.as_view(), name="dashboard"),
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

    # Adiciona aqui a rota de primeiro acesso
    path("primeiro-acesso/", views.primeiro_acesso_token_view, name="primeiro_acesso_token"),
    path("primeiro-acesso/trocar/", views.trocar_senha_primeiro_acesso, name="trocar_senha_primeiro_acesso"),
    path("assumir-unidade/<int:id>/", views.assumir_unidade, name="assumir_unidade"),
    path('voltar-contexto/', views.voltar_contexto, name='voltar_contexto'),

    
  

]