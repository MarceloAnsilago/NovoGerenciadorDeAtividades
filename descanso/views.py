# descanso/views.py
from calendar import monthrange
from collections import Counter
from datetime import date
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_protect

from servidores.models import Servidor
from .models import Descanso, Feriado, FeriadoCadastro
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

MONTH_NAMES_PT = (
    "Janeiro", "Fevereiro", "Março", "Abril",
    "Maio", "Junho", "Julho", "Agosto",
    "Setembro", "Outubro", "Novembro", "Dezembro",
)


def _get_requested_year(request):
    try:
        return int(request.GET.get("ano") or timezone.localdate().year)
    except (TypeError, ValueError):
        return timezone.localdate().year


def _build_descanso_month_filters(year, include_nodate=False):
    filters = [
        {"key": f"{year}-{month:02d}", "label": f"{MONTH_NAMES_PT[month - 1]} {year}"}
        for month in range(1, 13)
    ]
    if include_nodate:
        filters.append({"key": "nodate", "label": "Sem data"})
    return filters


def _get_descanso_month_keys(descanso, year):
    inicio = getattr(descanso, "data_inicio", None)
    fim = getattr(descanso, "data_fim", None)
    if not inicio or not fim:
        return ["nodate"]

    ano_inicio = date(year, 1, 1)
    ano_fim = date(year, 12, 31)
    inicio_filtrado = max(inicio, ano_inicio)
    fim_filtrado = min(fim, ano_fim)
    if inicio_filtrado > fim_filtrado:
        return []

    keys = []
    mes_atual = inicio_filtrado.month
    ano_atual = inicio_filtrado.year
    while True:
        keys.append(f"{ano_atual}-{mes_atual:02d}")
        if ano_atual == fim_filtrado.year and mes_atual == fim_filtrado.month:
            break
        if mes_atual == 12:
            mes_atual = 1
            ano_atual += 1
        else:
            mes_atual += 1
    return keys

@login_required
def lista_servidores(request):
    hoje = timezone.localdate()
    unidade_id = get_unidade_atual_id(request)

    servidores = Servidor.objects.select_related("unidade").filter(ativo=True)
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

    cadastros_por_ano = []
    if unidade_id:
        cadastros = list(
            FeriadoCadastro.objects.filter(unidade_id=unidade_id).order_by("-criado_em", "-id")
        )
        bucket = {}
        for cadastro in cadastros:
            ano = getattr(cadastro.criado_em, "year", None) or hoje.year
            bucket.setdefault(ano, []).append(cadastro)
        for ano in sorted(bucket.keys(), reverse=True):
            cadastros_por_ano.append({"ano": ano, "cadastros": bucket[ano]})

    return render(
        request,
        "descanso/lista.html",
        {
            "servidores": servidores,
            "cadastros_por_ano": cadastros_por_ano,
            "mes_hoje": hoje.strftime("%Y-%m"),
            "ano_hoje": hoje.year,
        },
    )


@login_required
def feriados(request):
    unidade_id = get_unidade_atual_id(request)
    cadastros = []
    if unidade_id:
        cadastros = list(
            FeriadoCadastro.objects.filter(unidade_id=unidade_id).order_by("-criado_em", "-id")
        )
    return render(request, "descanso/feriados.html", {"cadastros": cadastros})


def _parse_iso_date(raw: str):
    try:
        return date.fromisoformat((raw or "").strip()[:10])
    except Exception:
        return None


@login_required
@require_GET
def feriados_cadastros(request):
    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        return JsonResponse({"cadastros": []})
    cadastros = (
        FeriadoCadastro.objects.filter(unidade_id=unidade_id)
        .order_by("-criado_em", "-id")
        .values("id", "descricao")
    )
    return JsonResponse({"cadastros": list(cadastros)})


@login_required
@require_GET
def feriados_feed(request):
    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        return JsonResponse([], safe=False)

    cadastro_id = request.GET.get("cadastro_id")
    start = _parse_iso_date(request.GET.get("start") or "")
    end = _parse_iso_date(request.GET.get("end") or "")

    qs = Feriado.objects.select_related("cadastro").filter(cadastro__unidade_id=unidade_id)
    if cadastro_id:
        qs = qs.filter(cadastro_id=cadastro_id)
    if start:
        qs = qs.filter(data__gte=start)
    if end:
        qs = qs.filter(data__lte=end)

    if cadastro_id:
        data = [
            {
                "id": f.id,
                "title": f.descricao or "Feriado",
                "start": f.data.isoformat(),
                "allDay": True,
                "isHoliday": 1,
                "extendedProps": {
                    "kind": "feriado",
                    "descricao": f.descricao,
                    "cadastro": f.cadastro.descricao,
                    "cadastro_id": f.cadastro_id,
                },
            }
            for f in qs
        ]
        return JsonResponse(data, safe=False)

    by_date = {}
    for f in qs:
        key = f.data
        entry = by_date.setdefault(key, {"descricoes": [], "cadastros": []})
        label = f.descricao or "Feriado"
        if label not in entry["descricoes"]:
            entry["descricoes"].append(label)
        cadastro_label = f.cadastro.descricao
        if cadastro_label not in entry["cadastros"]:
            entry["cadastros"].append(cadastro_label)
        entry.setdefault("cadastro_ids", [])
        if f.cadastro_id not in entry["cadastro_ids"]:
            entry["cadastro_ids"].append(f.cadastro_id)

    data = []
    for day, entry in sorted(by_date.items(), key=lambda x: x[0]):
        descricoes = entry["descricoes"]
        cadastros = entry["cadastros"]
        label = "; ".join(descricoes)
        title = f"Feriado: {label}"
        cadastro_unico = cadastros[0] if len(cadastros) == 1 else ""
        cadastro_id_unico = entry["cadastro_ids"][0] if len(entry["cadastro_ids"]) == 1 else ""
        data.append(
            {
                "id": f"feriado-{day.isoformat()}",
                "title": title,
                "start": day.isoformat(),
                "allDay": True,
                "isHoliday": 1,
                "extendedProps": {
                    "kind": "feriado",
                    "descricoes": descricoes,
                    "cadastros": cadastros,
                    "cadastro": cadastro_unico,
                    "cadastro_id": cadastro_id_unico,
                },
            }
        )
    return JsonResponse(data, safe=False)


@login_required
@require_POST
@csrf_protect
def feriados_cadastro_novo(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = request.POST

    descricao = (payload.get("descricao") or "").strip()
    if not descricao:
        return JsonResponse({"ok": False, "error": "Descricao obrigatoria."}, status=400)

    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        return JsonResponse({"ok": False, "error": "Unidade nao definida."}, status=400)

    cadastro = FeriadoCadastro.objects.create(
        unidade_id=unidade_id,
        descricao=descricao,
        criado_por=request.user if request.user.is_authenticated else None,
    )
    return JsonResponse({"ok": True, "cadastro": {"id": cadastro.id, "descricao": cadastro.descricao}})


@login_required
@require_POST
@csrf_protect
def feriados_registrar(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = request.POST

    cadastro_id = payload.get("cadastro_id")
    data_str = payload.get("data")
    descricao = (payload.get("descricao") or "").strip()
    if not cadastro_id or not data_str or not descricao:
        return JsonResponse({"ok": False, "error": "Cadastro, data e descricao sao obrigatorios."}, status=400)

    try:
        cadastro_id = int(cadastro_id)
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "Cadastro invalido."}, status=400)

    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        return JsonResponse({"ok": False, "error": "Unidade nao definida."}, status=400)

    cadastro = get_object_or_404(FeriadoCadastro, pk=cadastro_id, unidade_id=unidade_id)
    data_ref = _parse_iso_date(data_str)
    if not data_ref:
        return JsonResponse({"ok": False, "error": "Data invalida."}, status=400)

    feriado, created = Feriado.objects.get_or_create(
        cadastro=cadastro,
        data=data_ref,
        defaults={
            "criado_por": request.user if request.user.is_authenticated else None,
            "descricao": descricao,
        },
    )
    if not created and feriado.descricao != descricao:
        Feriado.objects.filter(pk=feriado.pk).update(descricao=descricao)
        feriado.descricao = descricao
    return JsonResponse({"ok": True, "created": created, "feriado_id": feriado.id})


@login_required
@require_POST
@csrf_protect
def feriados_excluir(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = request.POST

    feriado_id = payload.get("feriado_id")
    if not feriado_id:
        return JsonResponse({"ok": False, "error": "Feriado nao informado."}, status=400)

    try:
        feriado_id = int(feriado_id)
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "Feriado invalido."}, status=400)

    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        return JsonResponse({"ok": False, "error": "Unidade nao definida."}, status=400)

    feriado = get_object_or_404(Feriado, pk=feriado_id, cadastro__unidade_id=unidade_id)
    feriado.delete()
    return JsonResponse({"ok": True})


@login_required
def feriados_cadastro_excluir(request, cadastro_id: int):
    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        messages.error(request, "Unidade nao definida.")
        return redirect(reverse("descanso:lista_servidores"))

    cadastro = get_object_or_404(FeriadoCadastro, pk=cadastro_id, unidade_id=unidade_id)
    feriados_count = cadastro.feriados.count()
    back_url = request.GET.get("next") or request.META.get("HTTP_REFERER") or reverse("descanso:lista_servidores")

    if request.method == "POST":
        descricao = cadastro.descricao
        cadastro.delete()
        messages.success(
            request,
            f"Cadastro '{descricao}' excluido com sucesso. {feriados_count} feriado(s) removido(s).",
        )
        return redirect(reverse("descanso:lista_servidores"))

    return render(
        request,
        "descanso/feriados_cadastro_excluir.html",
        {
            "cadastro": cadastro,
            "feriados_count": feriados_count,
            "back_url": back_url,
        },
    )


@login_required
def feriados_relatorio_mapa(request):
    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        messages.error(request, "Selecione uma unidade para visualizar os feriados.")
        return redirect(reverse("descanso:lista_servidores"))

    try:
        ano = int(request.GET.get("ano") or timezone.localdate().year)
    except (TypeError, ValueError):
        ano = timezone.localdate().year

    cadastro = None
    cadastro_id = request.GET.get("cadastro")
    if cadastro_id:
        try:
            cadastro_id = int(cadastro_id)
        except (TypeError, ValueError):
            cadastro_id = None
        if cadastro_id:
            cadastro = get_object_or_404(FeriadoCadastro, pk=cadastro_id, unidade_id=unidade_id)

    qs = (
        Feriado.objects.select_related("cadastro")
        .filter(cadastro__unidade_id=unidade_id, data__year=ano)
        .order_by("data", "id")
    )
    if cadastro:
        qs = qs.filter(cadastro=cadastro)

    feriados = list(qs)
    month_map = {}
    for f in feriados:
        month_map.setdefault(f.data.month, [])
        month_map[f.data.month].append(f)

    meses_label = [
        (1, "Janeiro"), (2, "Fevereiro"), (3, "Marco"), (4, "Abril"),
        (5, "Maio"), (6, "Junho"), (7, "Julho"), (8, "Agosto"),
        (9, "Setembro"), (10, "Outubro"), (11, "Novembro"), (12, "Dezembro"),
    ]

    meses_data = []
    for mes, nome in meses_label:
        feriados_mes = month_map.get(mes) or []
        if not feriados_mes:
            continue
        dias_marcados = {f.data.day for f in feriados_mes if f.data}
        ndias = monthrange(ano, mes)[1]
        dias = []
        for d in range(1, ndias + 1):
            dia_data = date(ano, mes, d)
            dias.append({
                "num": d,
                "marked": d in dias_marcados,
                "weekend": dia_data.weekday() >= 5,
            })
        legenda = []
        for f in feriados_mes:
            data_label = f.data.strftime("%d/%m/%Y")
            descricao = f.descricao or "Feriado"
            cadastro_label = f.cadastro.descricao if f.cadastro else ""
            legenda.append({
                "data": data_label,
                "descricao": descricao,
                "cadastro": cadastro_label,
            })
        meses_data.append({"mes_num": mes, "mes_nome": nome, "dias": dias, "legenda": legenda})

    anos_set = set(
        Feriado.objects.filter(cadastro__unidade_id=unidade_id)
        .values_list("data__year", flat=True)
    )
    if cadastro:
        anos_set = set(
            Feriado.objects.filter(cadastro=cadastro)
            .values_list("data__year", flat=True)
        )
    anos_set.discard(None)
    anos_opcoes = sorted(anos_set) if anos_set else [ano]
    if ano not in anos_opcoes:
        anos_opcoes.append(ano)
        anos_opcoes.sort()

    return render(
        request,
        "descanso/feriados_mapa.html",
        {
            "ano": ano,
            "anos_opcoes": anos_opcoes,
            "meses_data": meses_data,
            "cadastro": cadastro,
        },
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
    ano = _get_requested_year(request)
    inicio_ano = date(ano, 1, 1)
    fim_ano = date(ano, 12, 31)
    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        messages.error(request, "Selecione uma unidade para visualizar os descansos.")
        return redirect(reverse("descanso:lista_servidores"))

    qs = (Descanso.objects
          .select_related("servidor", "servidor__unidade")
          .filter(servidor__unidade_id=unidade_id))
    qs = qs.filter(data_inicio__lte=fim_ano, data_fim__gte=inicio_ano)

    qs = qs.order_by("-data_inicio", "-id")
    descansos = list(qs)

    has_nodate = False
    for descanso in descansos:
        keys = _get_descanso_month_keys(descanso, ano)
        descanso.month_keys = keys
        if "nodate" in keys:
            has_nodate = True

    month_filters = _build_descanso_month_filters(ano, include_nodate=has_nodate)
    month_counts = Counter()
    for descanso in descansos:
        for key in descanso.month_keys:
            month_counts[key] += 1
    for mf in month_filters:
        mf["count"] = month_counts.get(mf["key"], 0)
    month_keys = [mf["key"] for mf in month_filters]
    month_param = (request.GET.get("month") or "").strip()
    month_default = ""
    if month_param and month_param in month_keys:
        month_default = month_param
    elif month_keys:
        today_key = f"{hoje.year}-{hoje.month:02d}"
        if ano == hoje.year and today_key in month_keys:
            month_default = today_key
        else:
            month_default = month_keys[0]

    anos_disponiveis = set()
    q_anos = Descanso.objects.filter(servidor__unidade_id=unidade_id).values_list(
        "data_inicio__year", "data_fim__year"
    )
    for inicio_ano_val, fim_ano_val in q_anos:
        if inicio_ano_val:
            anos_disponiveis.add(inicio_ano_val)
        if fim_ano_val:
            anos_disponiveis.add(fim_ano_val)
    if not anos_disponiveis:
        anos_disponiveis.add(ano)
    else:
        anos_disponiveis.add(ano)
    anos_opcoes = sorted(anos_disponiveis)

    return render(
        request,
        "descanso/descansos_unidade.html",
        {
            "descansos": descansos,
            "month_filters": month_filters,
            "month_default": month_default,
            "ano": ano,
            "anos_opcoes": anos_opcoes,
            "total_descansos": len(descansos),
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
    servidores_qs = Servidor.objects.select_related("unidade").filter(ativo=True)
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

    anos_disponiveis = set()
    q_anos = Descanso.objects.filter(servidor__in=servidores_qs).values_list("data_inicio__year", "data_fim__year")
    for inicio_ano_val, fim_ano_val in q_anos:
        if inicio_ano_val:
            anos_disponiveis.add(inicio_ano_val)
        if fim_ano_val:
            anos_disponiveis.add(fim_ano_val)
    if not anos_disponiveis:
        anos_disponiveis.add(ano)
    else:
        anos_disponiveis.add(ano)
    anos_opcoes = sorted(anos_disponiveis)

    ctx = {"ano": ano, "anos_opcoes": anos_opcoes, "meses_data": meses_data}
    return render(request, "descanso/relatorio_mapa.html", ctx)
