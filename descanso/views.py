# descanso/views.py
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Exists, OuterRef, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from servidores.models import Servidor
from .models import Descanso
from .forms import DescansoForm
from core.utils import get_unidade_atual_id


@login_required
def lista_servidores(request):
    hoje = timezone.localdate()
    unidade_id = get_unidade_atual_id(request)

    servidores = Servidor.objects.select_related("unidade")
    if unidade_id:
        servidores = servidores.filter(unidade_id=unidade_id)
    else:
        messages.warning(
            request,
            "Contexto de unidade não definido. Selecione uma unidade."
        )
        servidores = servidores.none()

    descanso_ativo_qs = Descanso.objects.filter(
        servidor_id=OuterRef("pk"),
        data_inicio__lte=hoje,
        data_fim__gte=hoje,
    )
    servidores = servidores.annotate(tem_descanso_ativo=Exists(descanso_ativo_qs))

    return render(request, "descanso/lista.html", {"servidores": servidores})


@login_required
def criar_descanso(request):
    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        messages.error(request, "Defina a unidade atual antes de inserir descanso.")
        return redirect(reverse("descanso:lista_servidores"))

    servidor_id = request.GET.get("servidor_id")
    initial = {}
    if servidor_id:
        servidor = get_object_or_404(Servidor, pk=servidor_id, unidade_id=unidade_id)
        initial["servidor"] = servidor

    if request.method == "POST":
        form = DescansoForm(request.POST, request=request)
        if form.is_valid():
            obj = form.save(commit=False)
            if request.user.is_authenticated:
                obj.criado_por = request.user
            obj.save()
            messages.success(request, "Descanso inserido com sucesso.")
            return redirect(reverse("descanso:lista_servidores"))
        messages.error(request, "Revise os erros no formulário.")
    else:
        form = DescansoForm(request=request, initial=initial)

    return render(request, "descanso/criar.html", {"form": form})


@login_required
def descansos_unidade(request):
    """Lista de descansos da UNIDADE atual, com filtros."""
    hoje = timezone.localdate()
    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        messages.error(request, "Selecione uma unidade para visualizar os descansos.")
        return redirect(reverse("descanso:lista_servidores"))

    qs = (Descanso.objects
          .select_related("servidor", "servidor__unidade")
          .filter(servidor__unidade_id=unidade_id))

    status = request.GET.get("status", "ativos")  # ativos|futuros|finalizados|todos
    tipo = request.GET.get("tipo")
    inicio = request.GET.get("inicio")
    fim = request.GET.get("fim")
    q = request.GET.get("q")

    if status == "ativos":
        qs = qs.filter(data_inicio__lte=hoje, data_fim__gte=hoje)
    elif status == "futuros":
        qs = qs.filter(data_inicio__gt=hoje)
    elif status == "finalizados":
        qs = qs.filter(data_fim__lt=hoje)

    if tipo:
        qs = qs.filter(tipo=tipo)
    if inicio:
        qs = qs.filter(data_fim__gte=inicio)
    if fim:
        qs = qs.filter(data_inicio__lte=fim)
    if q:
        qs = qs.filter(Q(servidor__nome__icontains=q) | Q(observacoes__icontains=q))

    qs = qs.order_by("-data_inicio", "-id")

    base = Descanso.objects.filter(servidor__unidade_id=unidade_id)
    counts = {
        "ativos": base.filter(data_inicio__lte=hoje, data_fim__gte=hoje).count(),
        "futuros": base.filter(data_inicio__gt=hoje).count(),
        "finalizados": base.filter(data_fim__lt=hoje).count(),
        "todos": base.count(),
    }

    return render(
        request,
        "descanso/descansos_unidade.html",
        {
            "descansos": qs,
            "status": status,
            "counts": counts,
            "tipos": Descanso.Tipo.choices,
            "filtros": {"tipo": tipo, "inicio": inicio, "fim": fim, "q": q},
        },
    )


@login_required
def descansos_servidor(request, servidor_id: int):
    """Histórico de descansos de um servidor (da unidade atual)."""
    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        messages.error(request, "Selecione uma unidade para visualizar os descansos.")
        return redirect(reverse("descanso:lista_servidores"))

    servidor = get_object_or_404(Servidor, pk=servidor_id, unidade_id=unidade_id)

    hoje = timezone.localdate()
    qs = servidor.descansos.select_related("servidor").all()

    status = request.GET.get("status", "todos")
    tipo = request.GET.get("tipo")
    inicio = request.GET.get("inicio")
    fim = request.GET.get("fim")
    q = request.GET.get("q")

    if status == "ativos":
        qs = qs.filter(data_inicio__lte=hoje, data_fim__gte=hoje)
    elif status == "futuros":
        qs = qs.filter(data_inicio__gt=hoje)
    elif status == "finalizados":
        qs = qs.filter(data_fim__lt=hoje)

    if tipo:
        qs = qs.filter(tipo=tipo)
    if inicio:
        qs = qs.filter(data_fim__gte=inicio)
    if fim:
        qs = qs.filter(data_inicio__lte=fim)
    if q:
        qs = qs.filter(Q(observacoes__icontains=q))

    qs = qs.order_by("-data_inicio", "-id")

    counts = {
        "ativos": servidor.descansos.filter(data_inicio__lte=hoje, data_fim__gte=hoje).count(),
        "futuros": servidor.descansos.filter(data_inicio__gt=hoje).count(),
        "finalizados": servidor.descansos.filter(data_fim__lt=hoje).count(),
        "todos": servidor.descansos.count(),
    }

    return render(
        request,
        "descanso/servidor_descansos.html",
        {
            "servidor": servidor,
            "descansos": qs,
            "status": status,
            "counts": counts,
            "tipos": Descanso.Tipo.choices,
            "filtros": {"tipo": tipo, "inicio": inicio, "fim": fim, "q": q},
        },
    )
@login_required
def editar_descanso(request, pk: int):
    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        messages.error(request, "Defina a unidade atual.")
        return redirect("descanso:lista_servidores")

    obj = get_object_or_404(Descanso, pk=pk, servidor__unidade_id=unidade_id)

    if request.method == "POST":
        form = DescansoForm(request.POST, request=request, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Descanso atualizado com sucesso.")
            next_url = request.POST.get("next")
            return redirect(next_url or reverse("descanso:descansos_unidade"))
        messages.error(request, "Revise os erros no formulário.")
    else:
        form = DescansoForm(request=request, instance=obj)

    return render(request, "descanso/editar.html", {"form": form, "obj": obj, "next": request.GET.get("next")})


@login_required
def excluir_descanso(request, pk: int):
    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        messages.error(request, "Defina a unidade atual.")
        return redirect("descanso:lista_servidores")

    obj = get_object_or_404(Descanso, pk=pk, servidor__unidade_id=unidade_id)

    if request.method == "POST":
        next_url = request.POST.get("next")
        obj.delete()
        messages.success(request, "Descanso excluído com sucesso.")
        return redirect(next_url or reverse("descanso:descansos_unidade"))

    return render(request, "descanso/excluir.html", {"obj": obj, "next": request.GET.get("next")})