# core/admin_urls.py
from django.urls import path
from . import views

app_name = 'core_admin'

urlpatterns = [
    path('perfis/criar/', views.criar_perfil, name='criar_perfil'),
]