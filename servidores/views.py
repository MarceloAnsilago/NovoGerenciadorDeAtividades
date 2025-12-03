from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.utils.http import url_has_allowed_host_and_scheme

from core.utils import _get_unidade_atual  # seu util
from .forms import CargoForm, ServidorForm
from .models import Cargo, Servidor


def _get_safe_next(request):
    next_candidate = request.POST.get("next") or request.GET.get("next")
    if next_candidate and url_has_allowed_host_and_scheme(next_candidate, allowed_hosts={request.get_host()}):
        return next_candidate
    return ""


@login_required
def lista(request):
    unidade = _get_unidade_atual(request)
    qs = Servidor.objects.select_related("cargo").all().order_by("nome")
    if unidade:
        qs = qs.filter(unidade=unidade)

    q = (request.GET.get("q") or "").strip()
    raw_status = request.GET.get("status")
    if raw_status is None:
        status = "ativos"
    else:
        status = raw_status.strip().lower()
    if q:
        qs = qs.filter(Q(nome__icontains=q) | Q(matricula__icontains=q) | Q(telefone__icontains=q))
    if status == "ativos":
        qs = qs.filter(ativo=True)
    elif status == "inativos":
        qs = qs.filter(ativo=False)

    # POST = criar
    if request.method == "POST":
        # exige que exista unidade no contexto
        if not unidade:
            messages.warning(request, "Selecione uma unidade antes de cadastrar.")
            return redirect("servidores:lista")

        form = ServidorForm(request.POST)
        if form.is_valid():
            # salva commit=False para garantir atribuições obrigatórias (unidade etc.)
            serv = form.save(commit=False)

            # Preferência: se o form tem campo 'unidade' e o usuário selecionou um valor válido,
            # respeitamos; caso contrário, forçamos a unidade atual do contexto.
            selected_unidade = None
            try:
                # cleaned_data existe apenas após form.is_valid(), então é seguro
                selected_unidade = form.cleaned_data.get("unidade")
            except Exception:
                selected_unidade = None

            if selected_unidade:
                serv.unidade = selected_unidade
            else:
                # força a unidade do contexto (impede unidade=NULL)
                serv.unidade = unidade

            # salva dentro de transação e captura erro de integridade para mensagem amigável
            try:
                with transaction.atomic():
                    serv.save()
            except IntegrityError as exc:
                # log opcional: print(exc) ou logger.exception(exc)
                messages.error(request, "Erro ao salvar o servidor: problema de integridade. Verifique os dados e tente novamente.")
                return redirect("servidores:lista")

            messages.success(request, "Servidor cadastrado com sucesso.")
            return redirect("servidores:lista")
        else:
            messages.error(request, "Corrija os erros do formulário.")
    else:
        # GET -> instanciar form: podemos ocultar o campo 'unidade' na criação para evitar confusão
        form = ServidorForm()
        # opcional: ocultar o campo unidade para criação (se desejar forçar o contexto)
        # try:
        #     form.fields.pop("unidade", None)
        # except Exception:
        #     pass

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


@login_required
def cargos_lista(request):
    form = CargoForm(request.POST or None)
    cargos = Cargo.objects.all().order_by("nome")
    next_url = _get_safe_next(request)
    if request.method == "POST":
        if form.is_valid():
            form.save()
            messages.success(request, "Cargo cadastrado com sucesso.")
            if next_url:
                return redirect(next_url)
            return redirect("servidores:cargos_lista")
        messages.error(request, "Corrija os erros abaixo.")
    context = {"form": form, "cargos": cargos, "next_url": next_url}
    return render(request, "servidores/cargos/lista.html", context)


@login_required
def cargo_editar(request, pk):
    cargo = get_object_or_404(Cargo, pk=pk)
    next_url = _get_safe_next(request)
    if request.method == "POST":
        form = CargoForm(request.POST, instance=cargo)
        if form.is_valid():
            form.save()
            messages.success(request, "Cargo atualizado com sucesso.")
            if next_url:
                return redirect(next_url)
            return redirect("servidores:cargos_lista")
        messages.error(request, "Corrija os erros abaixo.")
    else:
        form = CargoForm(instance=cargo)
    return render(request, "servidores/cargos/editar.html", {"form": form, "object": cargo, "next_url": next_url})
