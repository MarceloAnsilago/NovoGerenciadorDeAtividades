from django.urls import path
from .views import metas_unidade_view
from .views import metas_unidade_view, atividades_lista_view
app_name = "metas"
from . import views
urlpatterns = [
    path('atividades/', atividades_lista_view, name='atividades-lista'),
    path('unidade/', metas_unidade_view, name='metas-unidade'),
    path("definir/<int:atividade_id>/", views.definir_meta_view, name="definir-meta"),
]