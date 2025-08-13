from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from .views_auth import MustChangePasswordView, MustChangePasswordDoneView

app_name = 'core'

urlpatterns = [
    # 🌐 Página inicial / dashboard (LOGIN_REDIRECT_URL aponta pra cá)
    path('dashboard/', views.dashboard, name='dashboard'),

    # 🌳 Administração / árvore de nós
    path('arvore/', views.admin_arvore, name='admin_arvore'),
    path('nos-json/', views.nos_json, name='nos_json'),
    path('health/', views.health, name='health'),
    path('criar-raiz/', views.criar_raiz, name='criar_raiz'),

    # 🔁 Ajax
    path('ajax/criar-no/', views.ajax_criar_no, name='ajax_criar_no'),
    path('ajax/renomear-no/', views.ajax_renomear_no, name='ajax_renomear_no'),
    path('ajax/excluir-no/', views.ajax_excluir_no, name='ajax_excluir_no'),
    path('definir-tipo/', views.ajax_definir_tipo, name='definir_tipo'),

    # 👥 Perfis
    path('admin/perfis/criar/', views.criar_perfil, name='criar_perfil'),
    path('novo-perfil/', views.novo_perfil, name='novo_perfil'),

    # 🔐 Troca obrigatória de senha
    path("accounts/password-change/", MustChangePasswordView.as_view(), name="password_change"),
    path("accounts/password-change/done/", MustChangePasswordDoneView.as_view(), name="password_change_done"),


    # 🔐 Autenticação
    path('login/', auth_views.LoginView.as_view(
        template_name='registration/login.html',
        redirect_authenticated_user=True
    ), name='login'),

    path('logout/', views.sair, name='logout'),  # View personalizada que redireciona para 'core:login'
]
