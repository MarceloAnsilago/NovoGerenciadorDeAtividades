# veiculos/urls.py

from django.urls import path
from . import views

app_name = 'veiculos'

urlpatterns = [
    path('', views.lista_veiculos, name='lista'),
    path('<int:pk>/editar/', views.editar_veiculo, name='editar'),
    path('<int:pk>/ativar/', views.ativar_veiculo, name='ativar'),
    path('<int:pk>/inativar/', views.inativar_veiculo, name='inativar'),
]