from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Q
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import VeiculoForm
from .models import Veiculo
from core.utils import _get_unidade_atual
from django.views.decorators.http import require_GET
from django.http import JsonResponse


@login_required
def lista_veiculos(request: HttpRequest) -> HttpResponse:
    unidade = _get_unidade_atual(request)
    if not unidade:
        raise Http404("Unidade atual não definida para o usuário.")

    # Cadastro de novo veículo
    if request.method == "POST":
        form = VeiculoForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.unidade = unidade
            try:
                obj.save()
            except IntegrityError:
                form.add_error("placa", "Já existe um veículo com essa placa nesta unidade.")
            else:
                messages.success(request, "Veículo cadastrado com sucesso!")
                return redirect("veiculos:lista")
    else:
        form = VeiculoForm()

    # Filtros
    qs = Veiculo.objects.filter(unidade=unidade).order_by("nome")
    q = (request.GET.get("q") or "").strip()
    raw_status = request.GET.get("status")
    if raw_status is None:
        status = "ativos"
    else:
        status = (raw_status or "").strip()

    if q:
        qs = qs.filter(Q(nome__icontains=q) | Q(placa__icontains=q))
    if status == "ativos":
        qs = qs.filter(ativo=True)
    elif status == "inativos":
        qs = qs.filter(ativo=False)

    # Paginação
    paginator = Paginator(qs, 12)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)
    veiculos = page_obj.object_list

    # 👇 Defina ANTES de montar o contexto
    veiculos_ativos = Veiculo.objects.filter(unidade=unidade, ativo=True).order_by("nome")

    ctx = {
        "form": form,
        "veiculos": veiculos,
        "page_obj": page_obj,
        "unidade": unidade,
        "q": q,
        "status": status or "todos",
        "veiculos_ativos": veiculos_ativos,
    }
    return render(request, "veiculos/lista.html", ctx)



@login_required
def editar_veiculo(request: HttpRequest, pk: int) -> HttpResponse:
    unidade = _get_unidade_atual(request)
    if not unidade:
        raise Http404("Unidade atual não definida para o usuário.")

    veiculo = get_object_or_404(Veiculo, pk=pk, unidade=unidade)

    if request.method == "POST":
        form = VeiculoForm(request.POST, instance=veiculo)
        if form.is_valid():
            try:
                form.save()
            except IntegrityError:
                form.add_error("placa", "Já existe veículo com esta placa nesta unidade.")
            else:
                messages.success(request, "Veículo atualizado com sucesso!")
                return redirect("veiculos:lista")
    else:
        form = VeiculoForm(instance=veiculo)

    return render(request, "veiculos/editar.html", {"form": form, "veiculo": veiculo, "unidade": unidade})


@login_required
def ativar_veiculo(request: HttpRequest, pk: int) -> HttpResponse:
    unidade = _get_unidade_atual(request)
    if not unidade:
        raise Http404("Unidade atual não definida para o usuário.")
    veiculo = get_object_or_404(Veiculo, pk=pk, unidade=unidade)
    if not veiculo.ativo:
        veiculo.ativo = True
        veiculo.save(update_fields=["ativo"])
        messages.success(request, f"{veiculo.nome} foi ativado.")
    return redirect("veiculos:lista")


@login_required
def inativar_veiculo(request: HttpRequest, pk: int) -> HttpResponse:
    unidade = _get_unidade_atual(request)
    if not unidade:
        raise Http404("Unidade atual não definida para o usuário.")
    veiculo = get_object_or_404(Veiculo, pk=pk, unidade=unidade)
    if veiculo.ativo:
        veiculo.ativo = False
        veiculo.save(update_fields=["ativo"])
        messages.success(request, f"{veiculo.nome} foi inativado.")
    return redirect("veiculos:lista")


@require_GET
@login_required
def veiculos_json(request):
    unidade = _get_unidade_atual(request)
    if not unidade:
        return JsonResponse({"veiculos": []})

    veiculos = Veiculo.objects.filter(unidade=unidade, ativo=True).order_by("nome")
    data = [{"id": v.id, "nome": v.nome, "placa": v.placa} for v in veiculos]

    return JsonResponse({"veiculos": data})
