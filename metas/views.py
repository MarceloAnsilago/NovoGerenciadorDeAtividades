from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.core.paginator import Paginator

from core.utils import get_unidade_atual
from atividades.models import Atividade
from .models import MetaAlocacao
from .forms import MetaForm


@login_required
def metas_unidade_view(request):
    unidade = get_unidade_atual(request)
    atividade_id = request.GET.get('atividade')

    alocacoes = MetaAlocacao.objects.select_related('meta', 'meta__atividade').filter(unidade=unidade)

    if atividade_id:
        alocacoes = alocacoes.filter(meta__atividade__id=atividade_id)

    return render(request, 'metas/meta_lista.html', {
        'unidade': unidade,
        'alocacoes': alocacoes,
    })


@login_required
def atividades_lista_view(request):
    unidade = get_unidade_atual(request)
    atividades = Atividade.objects.filter(ativo=True).order_by('-criado_em')

    if unidade:
        atividades = atividades.filter(unidade_origem=unidade)

    # Filtros GET
    area = (request.GET.get("area") or "").strip()
    q = (request.GET.get("q") or "").strip()

    if area == Atividade.Area.ANIMAL:
        atividades = atividades.filter(Q(area=Atividade.Area.ANIMAL) | Q(area=Atividade.Area.ANIMAL_VEGETAL))
    elif area == Atividade.Area.VEGETAL:
        atividades = atividades.filter(Q(area=Atividade.Area.VEGETAL) | Q(area=Atividade.Area.ANIMAL_VEGETAL))
    elif area:
        atividades = atividades.filter(area=area)

    if q:
        atividades = atividades.filter(Q(titulo__icontains=q) | Q(descricao__icontains=q))

    return render(request, "metas/atividades_lista.html", {
        "unidade": unidade,
        "atividades": atividades,
        "areas": Atividade.Area.choices,
        "area_selected": area,
        "q": q,
    })


@login_required
def definir_meta_view(request, atividade_id):
    unidade = get_unidade_atual(request)
    atividade = get_object_or_404(Atividade, pk=atividade_id, unidade_origem=unidade)

    if request.method == "POST":
        form = MetaForm(request.POST)
        if form.is_valid():
            meta = form.save(commit=False)
            meta.atividade = atividade
            meta.criado_por = request.user
            meta.unidade = unidade
            meta.save()

            # Cria uma alocação padrão com a quantidade informada no formulário
            quantidade = form.cleaned_data.get('quantidade')
            if quantidade:
                from .models import MetaAlocacao
                MetaAlocacao.objects.create(meta=meta, unidade=unidade, quantidade_alocada=quantidade)

            messages.success(request, "Meta definida com sucesso.")
            return redirect("metas:metas-unidade")
    else:
        form = MetaForm()

    return render(request, "metas/definir_meta.html", {
        "atividade": atividade,
        "form": form,
        "unidade": unidade,
    })
