from django.urls import path
from . import views

app_name = "metas"

urlpatterns = [
    # lista de metas da unidade atual
    path("", views.metas_unidade_view, name="metas-unidade"),

    # lista de atividades (para abrir 'definir meta')
    path("atividades/", views.atividades_lista_view, name="atividades-lista"),

    # criar meta para uma atividade (form)
    path("definir/<int:atividade_id>/", views.definir_meta_view, name="definir-meta"),

    # editar meta (form)
    path("editar/<int:meta_id>/", views.editar_meta_view, name="editar"),

    # excluir meta (POST)
    path("excluir/<int:meta_id>/", views.excluir_meta_view, name="excluir-meta"),

    # encerrar meta (fluxo com estratificacao)
    path("encerrar/<int:meta_id>/", views.encerrar_meta_view, name="encerrar-meta"),

    # alternar encerrada/reabrir (POST)
    path("toggle/<int:meta_id>/", views.toggle_encerrada_view, name="toggle_encerrada"),

    # atribuir quantidades para uma meta
    path("atribuir/<int:meta_id>/", views.atribuir_meta_view, name="atribuir-meta"),

    path("meta/<int:meta_id>/redistribuir/<int:parent_aloc_id>/", views.redistribuir_meta_view, name="redistribuir-meta"),
]
