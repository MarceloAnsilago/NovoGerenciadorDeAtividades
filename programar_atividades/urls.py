from django.urls import path
from . import views

app_name = 'programar_atividades'

urlpatterns = [
    path('', views.calendar_view, name='calendar'),          # /calendar/
    path('events/', views.events_feed, name='events_feed'),  # /calendar/events/
]
