from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from metas.models import Meta
from core.utils import get_unidade_atual

@login_required
def minhas_metas_view(request):
    unidade = get_unidade_atual(request)
    
    if not unidade:
        messages.error(request, "Não foi possível determinar sua unidade atual.")
        return redirect("dashboard")

    metas = Meta.objects.filter(alocacoes__unidade=unidade).distinct().order_by('data_limite')

    return render(request, 'minhas_metas/lista_metas.html', {'metas': metas})
