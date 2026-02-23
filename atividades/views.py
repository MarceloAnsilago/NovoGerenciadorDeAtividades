# atividades/views.py
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import IntegrityError
from django.db.models import Q
from django.core.paginator import Paginator
from django.utils.http import url_has_allowed_host_and_scheme
from .forms import AreaForm, AtividadeForm
from .models import Area, Atividade
from core.utils import _get_unidade_atual


def _get_safe_next(request):
    next_candidate = request.POST.get("next") or request.GET.get("next")
    if next_candidate and url_has_allowed_host_and_scheme(next_candidate, allowed_hosts={request.get_host()}):
        return next_candidate
    return ""


@login_required
def lista(request):
    unidade = _get_unidade_atual(request)

    # base query (ordenada alfabeticamente por título)
    qs = Atividade.objects.all().order_by("titulo")
    if unidade:
        qs = qs.filter(unidade_origem=unidade)

    # --- Filtros GET ---
    area = (request.GET.get("area") or "").strip()
    raw_status = request.GET.get("status")
    if raw_status is None:
        status = "ATIVAS"
    else:
        status = raw_status.strip()
    q = (request.GET.get("q") or "").strip()

    # Filtro de área (inclusivo p/ Animal/Vegetal)
    if area == Area.CODE_ANIMAL:
        qs = qs.filter(Q(area__code=Area.CODE_ANIMAL) | Q(area__code=Area.CODE_ANIMAL_VEGETAL))
    elif area == Area.CODE_VEGETAL:
        qs = qs.filter(Q(area__code=Area.CODE_VEGETAL) | Q(area__code=Area.CODE_ANIMAL_VEGETAL))
    elif area:
        qs = qs.filter(area__code=area)

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
        "areas": Area.objects.filter(ativo=True).order_by("nome"),
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


@login_required
def areas_lista(request):
    next_url = _get_safe_next(request)
    form = AreaForm(request.POST or None)
    areas = Area.objects.all().order_by("nome")

    if request.method == "POST":
        if form.is_valid():
            form.save()
            messages.success(request, "Área cadastrada com sucesso.")
            if next_url:
                return redirect(next_url)
            return redirect("atividades:areas_lista")
        messages.error(request, "Corrija os erros abaixo.")

    context = {
        "form": form,
        "areas": areas,
        "next_url": next_url,
    }
    return render(request, "atividades/areas/lista.html", context)


@login_required
def area_editar(request, pk: int):
    area = get_object_or_404(Area, pk=pk)
    next_url = _get_safe_next(request)
    if request.method == "POST":
        form = AreaForm(request.POST, instance=area)
        if form.is_valid():
            form.save()
            messages.success(request, "Área atualizada com sucesso.")
            if next_url:
                return redirect(next_url)
            return redirect("atividades:areas_lista")
        messages.error(request, "Corrija os erros abaixo.")
    else:
        form = AreaForm(instance=area)

    return render(request, "atividades/areas/editar.html", {
        "form": form,
        "object": area,
        "next_url": next_url,
    })
