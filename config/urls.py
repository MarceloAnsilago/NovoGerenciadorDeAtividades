"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include


urlpatterns = [
    path("admin/", admin.site.urls),
    path('', include(('core.urls', 'core'), namespace='core')),
    path("controle-acesso/", include("controle_acesso.urls")),
    path("servidores/", include(("servidores.urls", "servidores"), namespace="servidores")),
    path('veiculos/', include('veiculos.urls', namespace='veiculos')),
    path("atividades/", include("atividades.urls")),
    path("descanso/", include("descanso.urls", namespace="descanso")),
    path("plantao/", include("plantao.urls")),
    path("metas/", include("metas.urls", namespace="metas")),
    path('minhas-metas/', include('minhas_metas.urls', namespace='minhas_metas')),
    path("calendar/", include(("programar_atividades.urls", "programar_atividades"), namespace="programar_atividades")),
    path("programar_atividades/", include("programar_atividades.urls")),
    path("calendar/", include("programar_atividades.urls")),
    path('programar_atividades/', include('programar_atividades.urls')), 
    path('programar/', include('programar_atividades.urls')),
    
]