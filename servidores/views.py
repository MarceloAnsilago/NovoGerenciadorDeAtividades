# servidores/views.py
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Q
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import ServidorForm
from .models import Servidor


def _get_unidade_atual(request: HttpRequest):
    """
    Obtém a unidade atual do usuário.
    Tenta user.userprofile.unidade (ou aliases), ou 'unidade_id' da sessão.
    """
    user = request.user
    for attr in ("userprofile", "profile", "perfil"):
        obj = getattr(user, attr, None)
        if obj and getattr(obj, "unidade_id", None):
            return obj.unidade
    uid = request.session.get("unidade_id")
    if uid:
        # Import tardio para evitar dependência circular
        try:
            from core.models import No
            return No.objects.filter(pk=uid).first()
        except Exception:
            return None
    return None


@login_required
def lista(request: HttpRequest) -> HttpResponse:
    """
    Mostra o formulário de cadastro e a lista de servidores da unidade atual.
    POST cria novo servidor na unidade atual.
    """
    unidade = _get_unidade_atual(request)
    if not unidade:
        raise Http404("Unidade atual não definida para o usuário.")

    # Criação
    if request.method == "POST":
        form = ServidorForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.unidade = unidade
            try:
                obj.save()
            except IntegrityError:
                form.add_error("matricula", "Já existe servidor com esta matrícula nesta unidade.")
            else:
                messages.success(request, "Servidor cadastrado com sucesso!")
                return redirect("servidores:lista")
    else:
        form = ServidorForm()

    # Filtros
    qs = Servidor.objects.filter(unidade=unidade).order_by("nome")
    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "todos").strip()

    if q:
        qs = qs.filter(Q(nome__icontains=q) | Q(matricula__icontains=q) | Q(telefone__icontains=q))
    if status == "ativos":
        qs = qs.filter(ativo=True)
    elif status == "inativos":
        qs = qs.filter(ativo=False)

    # Paginação opcional
    paginator = Paginator(qs, 12)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)
    servidores = page_obj.object_list

    ctx = {
        "form": form,
        "servidores": servidores,
        "page_obj": page_obj,
        "unidade": unidade,
        "q": q,
        "status": status or "todos",
    }
    return render(request, "servidores/lista.html", ctx)


@login_required
def editar(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Edita um servidor da unidade atual.
    """
    unidade = _get_unidade_atual(request)
    if not unidade:
        raise Http404("Unidade atual não definida para o usuário.")

    servidor = get_object_or_404(Servidor, pk=pk, unidade=unidade)

    if request.method == "POST":
        form = ServidorForm(request.POST, instance=servidor)
        if form.is_valid():
            try:
                form.save()
            except IntegrityError:
                form.add_error("matricula", "Já existe servidor com esta matrícula nesta unidade.")
            else:
                messages.success(request, "Servidor atualizado com sucesso!")
                return redirect("servidores:lista")
    else:
        form = ServidorForm(instance=servidor)

    return render(request, "servidores/editar.html", {"form": form, "servidor": servidor, "unidade": unidade})


@login_required
def ativar(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Marca servidor como ativo (GET/POST por simplicidade).
    """
    unidade = _get_unidade_atual(request)
    if not unidade:
        raise Http404("Unidade atual não definida para o usuário.")
    servidor = get_object_or_404(Servidor, pk=pk, unidade=unidade)
    if not servidor.ativo:
        servidor.ativo = True
        servidor.save(update_fields=["ativo"])
        messages.success(request, f"{servidor.nome} foi ativado.")
    return redirect("servidores:lista")


@login_required
def inativar(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Marca servidor como inativo (GET/POST por simplicidade).
    """
    unidade = _get_unidade_atual(request)
    if not unidade:
        raise Http404("Unidade atual não definida para o usuário.")
    servidor = get_object_or_404(Servidor, pk=pk, unidade=unidade)
    if servidor.ativo:
        servidor.ativo = False
        servidor.save(update_fields=["ativo"])
        messages.success(request, f"{servidor.nome} foi inativado.")
    return redirect("servidores:lista")
