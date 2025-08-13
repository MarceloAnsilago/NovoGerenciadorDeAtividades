# core/urls.py
from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('arvore/', views.admin_arvore, name='admin_arvore'),
    path('nos-json/', views.nos_json, name='nos_json'),
    path('health/', views.health, name='health'),
    path('criar-raiz/', views.criar_raiz, name='criar_raiz'),

    # Endpoints Ajax
    path('ajax/criar-no/', views.ajax_criar_no, name='ajax_criar_no'),
    path('ajax/renomear-no/', views.ajax_renomear_no, name='ajax_renomear_no'),
    path('ajax/excluir-no/', views.ajax_excluir_no, name='ajax_excluir_no'),
    path('definir-tipo/', views.ajax_definir_tipo, name='definir_tipo'),

    # 🔁 troque de 'painel/perfis/criar/' para:
    path('admin/perfis/criar/', views.criar_perfil, name='criar_perfil'),
]