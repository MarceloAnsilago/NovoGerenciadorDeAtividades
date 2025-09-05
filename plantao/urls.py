from django.urls import path
from . import views

app_name = "plantao"

urlpatterns = [
    path("lista/", views.lista_plantao, name="lista_plantao"),
    path("verificar-descanso/", views.verificar_descanso, name="verificar_descanso"),
    path("ver-plantoes/", views.ver_plantoes, name="ver_plantoes"),
    path("<int:pk>/detalhe-fragment/", views.plantao_detalhe_fragment, name="plantao_detalhe_fragment"),
    path("<int:pk>/excluir/", views.plantao_excluir, name="plantao_excluir"),
    path('imprimir/<int:pk>/', views.plantao_imprimir, name='imprimir_plantao'),
    path('pagina/', views.ver_plantoes, name='pagina_plantao'),
    path('api/servidores_por_intervalo/', views.servidores_por_intervalo, name='servidores_por_intervalo'),
]