from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Prefetch

from metas.models import Meta, MetaAlocacao
from core.utils import get_unidade_atual

@login_required
def minhas_metas_view(request):
    unidade = get_unidade_atual(request)
    if not unidade:
        messages.error(request, "Não foi possível determinar sua unidade atual.")
        return redirect("dashboard")

    # prefetch só as alocações desta unidade para evitar N+1
    aloc_qs = MetaAlocacao.objects.filter(unidade=unidade).select_related('unidade')
    metas = (
        Meta.objects
            .filter(Q(alocacoes__unidade=unidade) | Q(unidade_criadora=unidade))
            .distinct()
            .select_related('atividade', 'unidade_criadora', 'criado_por')
            .prefetch_related(Prefetch('alocacoes', queryset=aloc_qs, to_attr='alocacoes_para_unidade'))
            .order_by('data_limite')
    )

    return render(request, 'minhas_metas/lista_metas.html', {'metas': metas, 'unidade': unidade})
