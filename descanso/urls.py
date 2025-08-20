# descanso/urls.py
# descanso/urls.py
from django.urls import path
from .views import (
    lista_servidores,
    criar_descanso,
    descansos_unidade,
    descansos_servidor,
    editar_descanso,
    excluir_descanso,
)

app_name = "descanso"

urlpatterns = [
    path("", lista_servidores, name="lista_servidores"),
    path("novo/", criar_descanso, name="criar_descanso"),
    path("todos/", descansos_unidade, name="descansos_unidade"),
    path("servidor/<int:servidor_id>/", descansos_servidor, name="descansos_servidor"),
    path("editar/<int:pk>/", editar_descanso, name="editar_descanso"),   # <-- adicionado
    path("excluir/<int:pk>/", excluir_descanso, name="excluir_descanso"), # <-- adicionado
]