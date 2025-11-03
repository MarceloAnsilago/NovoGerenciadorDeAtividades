# descanso/views.py
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from servidores.models import Servidor
from .models import Descanso
from .forms import DescansoForm
from core.utils import get_unidade_atual_id
from programar.models import ProgramacaoItemServidor


def _get_programacao_conflicts(servidor, data_inicio, data_fim):
    if not servidor or not data_inicio or not data_fim:
        return []

    qs = (
        ProgramacaoItemServidor.objects.select_related("item", "item__programacao", "item__meta")
        .filter(
            servidor=servidor,
            item__programacao__data__gte=data_inicio,
            item__programacao__data__lte=data_fim,
        )
        .order_by("item__programacao__data", "item_id")
    )
    return list(qs)


def _format_conflicts(conflicts):
    payload = []
    for conflict in conflicts:
        item = conflict.item
        programacao = getattr(item, "programacao", None)
        meta = getattr(item, "meta", None)
        titulo_meta = None
        if meta is not None:
            titulo_meta = getattr(meta, "display_titulo", None) or getattr(meta, "titulo", None) or str(meta)
        payload.append(
            {
                "id": conflict.pk,
                "data": getattr(programacao, "data", None),
                "meta": titulo_meta or "Atividade",
                "observacao": getattr(item, "observacao", ""),
            }
        )
    return payload
from datetime import date
from collections import OrderedDict
from calendar import monthrange

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
    descanso_existe_qs = Descanso.objects.filter(servidor_id=OuterRef("pk"))
    servidores = servidores.annotate(
        tem_descanso_ativo=Exists(descanso_ativo_qs),
        tem_descanso_registrado=Exists(descanso_existe_qs),
    )

    return render(
        request,
        "descanso/lista.html",
        {"servidores": servidores},
    )


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
        confirm_remove = request.POST.get("confirm_remove_assignments") == "1"
        if form.is_valid():
            obj = form.save(commit=False)
            conflicts = _get_programacao_conflicts(obj.servidor, obj.data_inicio, obj.data_fim)

            if conflicts and not confirm_remove:
                messages.warning(
                    request,
                    "O servidor esta alocado em atividades durante o periodo selecionado. "
                    "Confirme a remocao para prosseguir.",
                )
                context = {
                    "form": form,
                    "conflict_assignments": _format_conflicts(conflicts),
                }
                return render(request, "descanso/criar.html", context)

            with transaction.atomic():
                if conflicts:
                    ProgramacaoItemServidor.objects.filter(pk__in=[c.pk for c in conflicts]).delete()
                if request.user.is_authenticated:
                    obj.criado_por = request.user
                obj.save()

            if conflicts:
                messages.info(
                    request,
                    f"{len(conflicts)} vinculo(s) com atividades foram removidos para registrar o descanso.",
                )
            messages.success(request, "Descanso inserido com sucesso.")
            return redirect(reverse("descanso:lista_servidores"))
        messages.error(request, "Revise os erros no formulario.")
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
    next_url = request.POST.get("next") or request.GET.get("next")

    if request.method == "POST":
        form = DescansoForm(request.POST, request=request, instance=obj)
        confirm_remove = request.POST.get("confirm_remove_assignments") == "1"
        if form.is_valid():
            updated = form.save(commit=False)
            conflicts = _get_programacao_conflicts(updated.servidor, updated.data_inicio, updated.data_fim)

            if conflicts and not confirm_remove:
                messages.warning(
                    request,
                    "O servidor esta alocado em atividades durante o periodo selecionado. "
                    "Confirme a remocao para prosseguir.",
                )
                context = {
                    "form": form,
                    "obj": obj,
                    "next": next_url,
                    "conflict_assignments": _format_conflicts(conflicts),
                }
                return render(request, "descanso/editar.html", context)

            with transaction.atomic():
                if conflicts:
                    ProgramacaoItemServidor.objects.filter(pk__in=[c.pk for c in conflicts]).delete()
                updated.save()

            if conflicts:
                messages.info(
                    request,
                    f"{len(conflicts)} vinculo(s) com atividades foram removidos para registrar o descanso.",
                )
            messages.success(request, "Descanso atualizado com sucesso.")
            return redirect(next_url or reverse("descanso:descansos_unidade"))
        messages.error(request, "Revise os erros no formulario.")
    else:
        form = DescansoForm(request=request, instance=obj)

    return render(request, "descanso/editar.html", {"form": form, "obj": obj, "next": next_url})

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


@login_required
def relatorio_mapa(request):
    # ano escolhido (GET ?ano=YYYY) ou ano atual
    try:
        ano = int(request.GET.get("ano") or timezone.localdate().year)
    except (TypeError, ValueError):
        ano = timezone.localdate().year

    unidade_id = get_unidade_atual_id(request)
    servidores_qs = Servidor.objects.select_related("unidade")
    if unidade_id:
        servidores_qs = servidores_qs.filter(unidade_id=unidade_id)
    else:
        messages.warning(request, "Contexto de unidade não definido. Exibindo todas as unidades.")
    servidores_qs = servidores_qs.order_by("nome")

    # janela do ano
    inicio_ano = date(ano, 1, 1)
    fim_ano = date(ano, 12, 31)

    # descansos que tocam o ano selecionado
    descansos = (
        Descanso.objects
        .filter(servidor__in=servidores_qs, data_inicio__lte=fim_ano, data_fim__gte=inicio_ano)
        .select_related("servidor")
    )

    meses_label = [
        (1, "Janeiro"), (2, "Fevereiro"), (3, "Março"), (4, "Abril"),
        (5, "Maio"), (6, "Junho"), (7, "Julho"), (8, "Agosto"),
        (9, "Setembro"), (10, "Outubro"), (11, "Novembro"), (12, "Dezembro"),
    ]

    # mes_mapa[mes] = {"ndias": N, "rows": {servidor_id: {"servidor": Servidor, "dias":[bool]*N}}}
    mes_mapa = {}
    for mes, _ in meses_label:
        mes_mapa[mes] = {"ndias": monthrange(ano, mes)[1], "rows": {}}

    # marca os dias de cada descanso nos meses correspondentes
    for d in descansos:
        inicio = max(d.data_inicio, inicio_ano)
        fim = min(d.data_fim, fim_ano)
        for mes, _ in meses_label:
            ndias = mes_mapa[mes]["ndias"]
            mes_inicio = date(ano, mes, 1)
            mes_fim = date(ano, mes, ndias)
            s = max(inicio, mes_inicio)
            e = min(fim, mes_fim)
            if s <= e:
                rows = mes_mapa[mes]["rows"]
                row = rows.get(d.servidor_id)
                if row is None:
                    row = {"servidor": d.servidor, "dias": [False] * ndias}
                for dia in range(s.day, e.day + 1):
                    row["dias"][dia - 1] = True
                rows[d.servidor_id] = row

    # prepara dados ordenados por nome p/ template (lista, não dict)
    meses_data = []
    for mes, nome in meses_label:
        rows_dict = mes_mapa[mes]["rows"]
        rows = list(rows_dict.values())
        rows.sort(key=lambda r: r["servidor"].nome.lower())
        meses_data.append((mes, nome, rows))

    anos_opcoes = list(range(ano - 2, ano + 3))
    ctx = {"ano": ano, "anos_opcoes": anos_opcoes, "meses_data": meses_data}
    return render(request, "descanso/relatorio_mapa.html", ctx)
