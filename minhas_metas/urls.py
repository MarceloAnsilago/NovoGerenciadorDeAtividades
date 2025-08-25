from django.urls import path
from .views import minhas_metas_view

app_name = 'minhas_metas'



urlpatterns = [
    path('', minhas_metas_view, name='minhas_metas'),  # ou o nome que você preferir
]