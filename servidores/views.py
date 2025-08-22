# servidores/views.py
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.db.models import Q

from .forms import ServidorForm
from .models import Servidor
from core.utils import _get_unidade_atual

logger = logging.getLogger(__name__)


@login_required
def lista(request):
    """
    Lista e cria (POST) servidores.
    - GET: exibe lista + formulário de criação
    - POST: cria novo servidor (associa à unidade atual, se houver)
    """
    unidade = _get_unidade_atual(request)

    # query base e filtros
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

    # criação via POST
    if request.method == "POST":
        # se não há unidade, prevenir criação (se isso for regra do app)
        if not unidade:
            messages.warning(request, "Selecione uma unidade no contexto antes de cadastrar servidores.")
            return redirect("servidores:lista")

        form = ServidorForm(request.POST)
        if form.is_valid():
            serv = form.save(commit=False)
            # associe o campo de unidade conforme seu modelo (ajuste nome se diferente)
            if hasattr(serv, "unidade") and serv.unidade is None:
                serv.unidade = unidade
            serv.save()
            messages.success(request, "Servidor cadastrado com sucesso.")
            return redirect("servidores:lista")
        else:
            messages.error(request, "Corrija os erros no formulário antes de salvar.")
    else:
        form = ServidorForm()

    # paginação
    paginator = Paginator(qs, 12)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "form": form,
        "servidores": page_obj.object_list,
        "page_obj": page_obj,
        "unidade": unidade,
        "q": q,
        "status": status,
    }
    return render(request, "servidores/lista.html", context)


@login_required
def editar(request, pk: int):
    """
    Edita um servidor.
    GET: exibe formulário com dados.
    POST: salva alterações e redireciona para next (ou lista).
    """
    unidade = _get_unidade_atual(request)
    serv = get_object_or_404(Servidor, pk=pk)

    # segurança: se o app exige que só se altere servidores da unidade atual
    if unidade and getattr(serv, "unidade_id", None) != getattr(unidade, "id", None):
        messages.warning(request, "Você só pode editar servidores da unidade atual.")
        return redirect("servidores:lista")

    if request.method == "POST":
        form = ServidorForm(request.POST, instance=serv)
        if form.is_valid():
            form.save()
            messages.success(request, "Servidor atualizado com sucesso.")
            next_url = request.POST.get("next") or "servidores:lista"
            return redirect(next_url)
        else:
            messages.error(request, "Corrija os erros no formulário antes de salvar.")
    else:
        form = ServidorForm(instance=serv)

    context = {
        "form": form,
        "object": serv,
        "unidade": unidade,
        "next": request.GET.get("next", request.get_full_path()),
    }
    return render(request, "servidores/editar.html", context)


@login_required
@require_POST
def toggle_ativo(request, pk: int):
    """
    Altera o campo 'ativo' do servidor (toggle) — aceita apenas POST.
    Retorna para 'next' (se fornecido) ou para a lista.
    """
    unidade = _get_unidade_atual(request)
    serv = get_object_or_404(Servidor, pk=pk)

    logger.info("toggle_ativo called for Servidor %s by %s (unidade=%s) method=%s",
                pk, request.user, getattr(unidade, "id", None), request.method)

    if unidade and getattr(serv, "unidade_id", None) != getattr(unidade, "id", None):
        messages.warning(request, "Você só pode alterar status de servidores da unidade atual.")
        return redirect("servidores:lista")

    serv.ativo = not serv.ativo
    serv.save(update_fields=["ativo"])
    messages.success(request, f"Servidor {'ativado' if serv.ativo else 'inativado'} com sucesso.")
    return redirect(request.POST.get("next") or "servidores:lista")


@login_required
@require_POST
def excluir(request, pk: int):
    """
    Excluir servidor — exemplo de ação destrutiva protegida por POST.
    Use com cuidado; dependendo das regras do seu sistema talvez deva apenas marcar inativo.
    """
    unidade = _get_unidade_atual(request)
    serv = get_object_or_404(Servidor, pk=pk)

    if unidade and getattr(serv, "unidade_id", None) != getattr(unidade, "id", None):
        messages.warning(request, "Você só pode excluir servidores da unidade atual.")
        return redirect("servidores:lista")

    nome = serv.nome
    serv.delete()
    messages.success(request, f"Servidor {nome} excluído com sucesso.")
    return redirect(request.POST.get("next") or "servidores:lista")
@login_required
@require_POST
def inativar(request, pk: int):
    serv = get_object_or_404(Servidor, pk=pk)
    unidade = _get_unidade_atual(request)
    if unidade and getattr(serv, "unidade_id", None) != getattr(unidade, "id", None):
        messages.warning(request, "Você só pode alterar status de servidores da unidade atual.")
        return redirect("servidores:lista")
    if not serv.ativo:
        messages.info(request, f"Servidor {serv.nome} já está inativo.")
    else:
        serv.ativo = False
        serv.save(update_fields=["ativo"])
        messages.success(request, f"Servidor {serv.nome} inativado com sucesso.")
    return redirect(request.POST.get("next") or "servidores:lista")


@login_required
@require_POST
def ativar(request, pk: int):
    serv = get_object_or_404(Servidor, pk=pk)
    unidade = _get_unidade_atual(request)
    if unidade and getattr(serv, "unidade_id", None) != getattr(unidade, "id", None):
        messages.warning(request, "Você só pode alterar status de servidores da unidade atual.")
        return redirect("servidores:lista")
    if serv.ativo:
        messages.info(request, f"Servidor {serv.nome} já está ativo.")
    else:
        serv.ativo = True
        serv.save(update_fields=["ativo"])
        messages.success(request, f"Servidor {serv.nome} ativado com sucesso.")
    return redirect(request.POST.get("next") or "servidores:lista")