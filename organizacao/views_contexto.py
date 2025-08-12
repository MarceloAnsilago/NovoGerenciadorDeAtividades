# organizacao/views_contexto.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, get_object_or_404
from .models import PerfilUsuario
from .utils import set_contexto

@login_required
def trocar_contexto(request, vinculo_id:int):
    v = get_object_or_404(PerfilUsuario, pk=vinculo_id, usuario=request.user)
    set_contexto(request, v.id)
    return redirect(request.META.get("HTTP_REFERER") or "/")