# minhas_metas/urls.py
from django.urls import path
from . import views

app_name = "minhas_metas"

urlpatterns = [
    path("", views.minhas_metas_view, name="lista"),
    path("", views.minhas_metas_view, name="minhas_metas"),  # alias p/ {% url 'minhas_metas' %}
]