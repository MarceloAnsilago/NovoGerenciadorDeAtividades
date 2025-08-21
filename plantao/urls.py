from django.urls import path
from . import views

app_name = "plantao"

urlpatterns = [
    path("lista/", views.lista_plantao, name="lista_plantao"),
    path("verificar-descanso/", views.verificar_descanso, name="verificar_descanso"),
    path("ver-plantoes/", views.ver_plantoes, name="ver_plantoes"),
    path("<int:pk>/detalhe-fragment/", views.plantao_detalhe_fragment, name="plantao_detalhe_fragment"),
    path("<int:pk>/excluir/", views.plantao_excluir, name="plantao_excluir"),
    path("<int:pk>/imprimir/", views.plantao_imprimir, name="plantao_imprimir"),
]