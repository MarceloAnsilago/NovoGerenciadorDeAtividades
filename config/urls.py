# config/urls.py
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),

    path("", include(("core.urls", "core"), namespace="core")),
    path("controle-acesso/", include("controle_acesso.urls")),
    path("servidores/", include(("servidores.urls", "servidores"), namespace="servidores")),
    path("veiculos/", include(("veiculos.urls", "veiculos"), namespace="veiculos")),
    path("atividades/", include("atividades.urls")),
    path("descanso/", include(("descanso.urls", "descanso"), namespace="descanso")),
    path("plantao/", include("plantao.urls")),
    path("metas/", include(("metas.urls", "metas"), namespace="metas")),
    path("minhas-metas/", include(("minhas_metas.urls", "minhas_metas"), namespace="minhas_metas")),

    path("programar/", include(("programar.urls", "programar"), namespace="programar")),
]
