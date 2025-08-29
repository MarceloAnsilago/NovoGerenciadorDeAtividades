# programar_atividades/urls.py
from django.urls import path
from . import views

app_name = "programar_atividades"

urlpatterns = [
    path("", views.calendar_view, name="calendar"),                 # /calendar/
    path("events/", views.events_feed, name="events_feed"),         # /calendar/events/
    path("metas/", views.metas_disponiveis, name="metas_disponiveis"),  # /calendar/metas/
    path('ajax/servidores/', views.servidores_disponiveis_para_data, name='servidores_para_data'),
]