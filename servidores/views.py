from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.views.decorators.http import require_POST
from django.db.models import Q

from .models import Servidor
from .forms import ServidorForm
from core.utils import _get_unidade_atual  # seu util

@login_required
def lista(request):
    unidade = _get_unidade_atual(request)
    qs = Servidor.objects.all().order_by("nome")
    if unidade:
        qs = qs.filter(unidade=unidade)

    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip().lower()
    if q:
        qs = qs.filter(Q(nome__icontains=q) | Q(matricula__icontains=q) | Q(telefone__icontains=q))
    if status == "ativos":
        qs = qs.filter(ativo=True)
    elif status == "inativos":
        qs = qs.filter(ativo=False)

    # POST = criar
    if request.method == "POST":
        if not unidade:
            messages.warning(request, "Selecione uma unidade antes de cadastrar.")
            return redirect("servidores:lista")
        form = ServidorForm(request.POST)
        if form.is_valid():
            serv = form.save(commit=False)
            if hasattr(serv, "unidade") and serv.unidade is None:
                serv.unidade = unidade
            serv.save()
            messages.success(request, "Servidor cadastrado com sucesso.")
            return redirect("servidores:lista")
        else:
            messages.error(request, "Corrija os erros do formulário.")
    else:
        form = ServidorForm()

    paginator = Paginator(qs, 12)
    page_obj = paginator.get_page(request.GET.get("page"))
    context = {"form": form, "servidores": page_obj.object_list, "page_obj": page_obj,
               "unidade": unidade, "q": q, "status": status}
    return render(request, "servidores/lista.html", context)

@login_required
def editar(request, pk):
    unidade = _get_unidade_atual(request)
    serv = get_object_or_404(Servidor, pk=pk)
    if unidade and serv.unidade_id != unidade.id:
        messages.warning(request, "Você só pode editar servidores da unidade atual.")
        return redirect("servidores:lista")

    if request.method == "POST":
        form = ServidorForm(request.POST, instance=serv)
        if form.is_valid():
            form.save()
            messages.success(request, "Servidor atualizado com sucesso.")
            return redirect(request.POST.get("next") or "servidores:lista")
    else:
        form = ServidorForm(instance=serv)

    return render(request, "servidores/editar.html", {"form": form, "object": serv, "unidade": unidade, "next": request.GET.get("next", request.get_full_path())})

@login_required
@require_POST
def inativar(request, pk):
    serv = get_object_or_404(Servidor, pk=pk)
    unidade = _get_unidade_atual(request)
    if unidade and serv.unidade_id != unidade.id:
        messages.warning(request, "Você só pode alterar servidores da unidade atual.")
        return redirect("servidores:lista")
    if serv.ativo:
        serv.ativo = False
        serv.save(update_fields=["ativo"])
        messages.success(request, f"Servidor {serv.nome} inativado.")
    else:
        messages.info(request, f"Servidor {serv.nome} já está inativo.")
    return redirect(request.POST.get("next") or "servidores:lista")

@login_required
@require_POST
def ativar(request, pk):
    serv = get_object_or_404(Servidor, pk=pk)
    unidade = _get_unidade_atual(request)
    if unidade and serv.unidade_id != unidade.id:
        messages.warning(request, "Você só pode alterar servidores da unidade atual.")
        return redirect("servidores:lista")
    if not serv.ativo:
        serv.ativo = True
        serv.save(update_fields=["ativo"])
        messages.success(request, f"Servidor {serv.nome} ativado.")
    else:
        messages.info(request, f"Servidor {serv.nome} já está ativo.")
    return redirect(request.POST.get("next") or "servidores:lista")
