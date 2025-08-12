from django.urls import path
from .views_contexto import trocar_contexto
from .views_vinculos import (
    vinculos_lista, vinculos_novo, vinculos_editar, vinculos_excluir
)
from .views_stubs import (
    pagina_servidores, pagina_veiculos, pagina_descanso, pagina_plantao, pagina_metas
)
from .views_usuarios import usuarios_lista, usuarios_novo  # <-- aqui

app_name = "organizacao"

urlpatterns = [
    path("contexto/<int:vinculo_id>/", trocar_contexto, name="trocar_contexto"),

    # Vínculos
    path("vinculos/", vinculos_lista, name="vinculos_home"),
    path("vinculos/novo/", vinculos_novo, name="vinculos_novo"),
    path("vinculos/<int:pk>/editar/", vinculos_editar, name="vinculos_editar"),
    path("vinculos/<int:pk>/excluir/", vinculos_excluir, name="vinculos_excluir"),

    # Usuários
    path("usuarios/", usuarios_lista, name="usuarios_lista"),
    path("usuarios/novo/", usuarios_novo, name="usuarios_novo"),

    # Stubs (até os apps reais ficarem prontos)
    path("servidores/", pagina_servidores, name="pagina_servidores"),
    path("veiculos/", pagina_veiculos, name="pagina_veiculos"),
    path("descanso/", pagina_descanso, name="pagina_descanso"),
    path("plantao/", pagina_plantao, name="pagina_plantao"),
    path("metas/", pagina_metas, name="pagina_metas"),
]