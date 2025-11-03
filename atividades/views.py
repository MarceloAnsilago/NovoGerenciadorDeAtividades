# atividades/views.py
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import IntegrityError
from django.db.models import Q
from django.core.paginator import Paginator
from .forms import AtividadeForm
from .models import Atividade
from core.utils import _get_unidade_atual


@login_required
def lista(request):
    unidade = _get_unidade_atual(request)

    # base query (ordenada mais recentes primeiro)
    qs = Atividade.objects.all().order_by("-criado_em")
    if unidade:
        qs = qs.filter(unidade_origem=unidade)

    # --- Filtros GET ---
    area = (request.GET.get("area") or "").strip()
    status = (request.GET.get("status") or "").strip()
    q = (request.GET.get("q") or "").strip()

    # Filtro de área (inclusivo p/ Animal/Vegetal)
    if area == Atividade.Area.ANIMAL:
        qs = qs.filter(Q(area=Atividade.Area.ANIMAL) | Q(area=Atividade.Area.ANIMAL_VEGETAL))
    elif area == Atividade.Area.VEGETAL:
        qs = qs.filter(Q(area=Atividade.Area.VEGETAL) | Q(area=Atividade.Area.ANIMAL_VEGETAL))
    elif area:
        qs = qs.filter(area=area)

    # Filtro de status
    if status == "ATIVAS":
        qs = qs.filter(ativo=True)
    elif status == "INATIVAS":
        qs = qs.filter(ativo=False)

    # Busca por título/descrição
    if q:
        qs = qs.filter(Q(titulo__icontains=q) | Q(descricao__icontains=q))

    # --- POST = criar nova atividade ---
    if request.method == "POST":
        if not unidade:
            messages.warning(request, "Selecione uma unidade no contexto antes de cadastrar atividades.")
            return redirect("atividades:lista")

        form = AtividadeForm(request.POST)
        if form.is_valid():
            atividade = form.save(commit=False)
            atividade.unidade_origem = unidade
            atividade.criado_por = request.user
            try:
                atividade.save()
            except IntegrityError:
                form.add_error("titulo", "Já existe uma atividade com este título nesta unidade.")
            else:
                messages.success(request, "Atividade cadastrada com sucesso.")
                return redirect("atividades:lista")
    else:
        form = AtividadeForm()

    # --- Paginação ---
    paginator = Paginator(qs, 10)  # ajuste o tamanho da página se quiser
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "form": form,
        "atividades": page_obj.object_list,
        "page_obj": page_obj,
        "unidade": unidade,
        "areas": Atividade.Area.choices,
        "area_selected": area,
        "status_selected": status,
        "q": q,
    }
    return render(request, "atividades/lista.html", context)
@login_required
def editar(request, pk: int):
    unidade = _get_unidade_atual(request)
    obj = get_object_or_404(Atividade, pk=pk)

    # segurança: só pode editar atividades da unidade atual
    if unidade and obj.unidade_origem_id != unidade.id:
        messages.warning(request, "Você só pode editar atividades da unidade atual.")
        return redirect("atividades:lista")

    if request.method == "POST":
        form = AtividadeForm(request.POST, instance=obj)
        if form.is_valid():
            try:
                form.save()
            except IntegrityError:
                form.add_error("titulo", "Já existe uma atividade com este título nesta unidade.")
            else:
                messages.success(request, "Atividade atualizada com sucesso.")
                next_url = request.POST.get("next") or "atividades:lista"
                return redirect(next_url)
    else:
        form = AtividadeForm(instance=obj)

    return render(request, "atividades/editar.html", {
        "form": form,
        "atividade": obj,
        "unidade": unidade,
        "next": request.GET.get("next", request.get_full_path()),
    })


@login_required
@require_POST
def toggle_ativo(request, pk: int):
    unidade = _get_unidade_atual(request)
    obj = get_object_or_404(Atividade, pk=pk)

    if unidade and obj.unidade_origem_id != unidade.id:
        messages.warning(request, "Você só pode alterar status de atividades da unidade atual.")
        return redirect("atividades:lista")

    obj.ativo = not obj.ativo
    obj.save(update_fields=["ativo"])
    messages.success(request, f"Atividade {'ativada' if obj.ativo else 'inativada'} com sucesso.")
    return redirect(request.POST.get("next") or "atividades:lista")
