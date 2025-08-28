# minhas_metas/views.py
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from metas.models import MetaAlocacao
from core.utils import get_unidade_atual

@login_required
def minhas_metas_view(request):
    unidade = get_unidade_atual(request)
    if not unidade:
        messages.error(request, "Selecione uma unidade antes de ver as metas.")
        return redirect("core:dashboard")

    atividade_id = request.GET.get("atividade")

    alocacoes = (
        MetaAlocacao.objects
        .select_related("meta", "meta__atividade", "meta__criado_por", "meta__unidade_criadora")
        .filter(unidade=unidade)
        .order_by("meta__data_limite", "meta__titulo")
    )
    if atividade_id:
        alocacoes = alocacoes.filter(meta__atividade_id=atividade_id)

    tem_filhos = unidade.filhos.exists()

    return render(request, "minhas_metas/lista_metas.html", {
        "unidade": unidade,
        "alocacoes": alocacoes,
        "tem_filhos": tem_filhos,
    })
