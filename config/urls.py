# config/urls.py
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

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

    # ✅ novo app
    path("programar/", include(("programar.urls", "programar"), namespace="programar")),

    # ✅ antigo, com NAMESPACE registrado
    path("programar_atividades/", include(("programar_atividades.urls", "programar_atividades"),
                                          namespace="programar_atividades")),

    # (opcional) compat: /calendar -> tela antiga
    path("calendar/", RedirectView.as_view(pattern_name="programar_atividades:calendar", permanent=False)),
]