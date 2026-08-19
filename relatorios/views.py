from __future__ import annotations

from datetime import date, datetime

from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.db.models import Count, Max, Min, Q
from django.db.models.functions import TruncMonth
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from core.utils import get_unidade_atual_id
from programar.models import Programacao
from programar.models import ProgramacaoItem
from programar.status import ENCERRADA_AUTOMATICAMENTE_MARKER

from .services.programacao_report_service import build_programacao_report


def _parse_date(value: str):
    try:
        return datetime.strptime(str(value or "").strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def _meta_expediente_id() -> int | None:
    raw_id = getattr(settings, "META_EXPEDIENTE_ID", None)
    try:
        return int(raw_id) if raw_id is not None else None
    except (TypeError, ValueError):
        return None


def _build_programacoes_encerradas_periodos(request):
    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        return []

    today = timezone.localdate()
    rows = (
        Programacao.objects.filter(unidade_id=unidade_id)
        .annotate(mes=TruncMonth("data"))
        .values("mes")
        .annotate(
            data_inicial=Min("data"),
            data_final=Max("data"),
            dias_programados=Count("data", distinct=True),
            total_programacoes=Count("id"),
            total_encerradas=Count("id", filter=Q(concluida=True)),
        )
        .order_by("-mes")
    )
    periodos = []
    for row in rows:
        mes = row.get("mes")
        row["is_mes_atual"] = bool(mes and mes.year == today.year and mes.month == today.month)
        total_programacoes = int(row.get("total_programacoes") or 0)
        total_encerradas = int(row.get("total_encerradas") or 0)
        row["is_encerrado"] = total_programacoes > 0 and total_encerradas >= total_programacoes
        itens_qs = ProgramacaoItem.objects.filter(
            programacao__unidade_id=unidade_id,
            programacao__data__gte=row.get("data_inicial"),
            programacao__data__lte=row.get("data_final"),
        )
        meta_expediente_id = _meta_expediente_id()
        if meta_expediente_id is not None:
            itens_qs = itens_qs.exclude(meta_id=meta_expediente_id)
        origens_remarcadas_concluidas = _origens_remarcadas_concluidas_ids(itens_qs.values_list("id", flat=True))
        if origens_remarcadas_concluidas:
            itens_qs = itens_qs.exclude(id__in=origens_remarcadas_concluidas)
        item_counts = itens_qs.aggregate(
            total_atividades=Count("id"),
            concluidas=Count("id", filter=Q(concluido=True)),
            justificadas=Count("id", filter=Q(nao_realizada_justificada=True)),
            canceladas=Count("id", filter=Q(cancelada=True)),
            nao_realizadas=Count(
                "id",
                filter=Q(concluido=False, concluido_em__isnull=False, cancelada=False, nao_realizada_justificada=False),
            ),
            encerradas_auto=Count("id", filter=Q(observacao__contains=ENCERRADA_AUTOMATICAMENTE_MARKER)),
            encerradas_auto_abertas=Count(
                "id",
                filter=Q(
                    concluido=False,
                    cancelada=False,
                    nao_realizada_justificada=False,
                    observacao__contains=ENCERRADA_AUTOMATICAMENTE_MARKER,
                ),
            ),
            pendentes=Count(
                "id",
                filter=(
                    Q(concluido=False, concluido_em__isnull=True, cancelada=False, nao_realizada_justificada=False)
                    & ~Q(observacao__contains=ENCERRADA_AUTOMATICAMENTE_MARKER)
                ),
            ),
        )
        row.update({key: int(value or 0) for key, value in item_counts.items()})
        solucionadas = (
            row["concluidas"]
            + row["justificadas"]
            + row["canceladas"]
            + row["encerradas_auto_abertas"]
        )
        row["percentual_solucionado"] = round((solucionadas / row["total_atividades"]) * 100, 1) if row["total_atividades"] else 0
        periodos.append(row)
    return periodos


def _month_bounds(mes: date) -> tuple[date, date]:
    start = mes.replace(day=1)
    if start.month == 12:
        return start, date(start.year + 1, 1, 1)
    return start, date(start.year, start.month + 1, 1)


def _unidade_depth(unidade) -> int | None:
    if not unidade:
        return None
    depth = 0
    atual = unidade
    while getattr(atual, "parent_id", None):
        depth += 1
        atual = atual.parent
    return depth


def _itens_abertos_bloqueantes_q() -> Q:
    return Q(concluido=False, cancelada=False, nao_realizada_justificada=False)


def _origens_remarcadas_concluidas_ids(item_ids) -> set[int]:
    ids = [int(item_id) for item_id in item_ids if item_id]
    if not ids:
        return set()
    return {
        int(item_id)
        for item_id in ProgramacaoItem.objects.filter(
            remarcado_de_id__in=ids,
            concluido=True,
            cancelada=False,
        ).values_list("remarcado_de_id", flat=True)
        if item_id
    }


def pode_reabrir_programacao_mes(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    try:
        perfil = getattr(user, "userprofile", None)
    except Exception:
        perfil = None
    depth = _unidade_depth(getattr(perfil, "unidade", None))
    if depth is not None and depth <= 2:
        return True
    return user.has_perm("programar.reabrir_programacao_mes")


@login_required
@require_GET
def relatorios_home_view(request):
    return render(request, "relatorios/home.html")


@login_required
@require_GET
@never_cache
def relatorio_programacao_view(request):
    data_inicial_raw = (request.GET.get("data_inicial") or "").strip()
    data_final_raw = (request.GET.get("data_final") or "").strip()
    observacao_raw = (request.GET.get("observacao") or "")
    observacao = str(observacao_raw).replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(observacao) > 2000:
        observacao = observacao[:2000].rstrip()
    data_inicial = _parse_date(data_inicial_raw)
    data_final = _parse_date(data_final_raw)
    is_print = request.GET.get("print", "").strip().lower() in {"1", "true", "yes", "on"}
    report_tab = (request.GET.get("report_tab") or "programacao").strip().lower()
    if report_tab not in {"programacao", "encerradas"}:
        report_tab = "programacao"

    selected_sections = {
        "historico": request.GET.get("sec_historico", "1") not in {"0", "false", "off"},
        "desempenho": request.GET.get("sec_desempenho", "1") not in {"0", "false", "off"},
        "indicadores": request.GET.get("sec_indicadores", "1") not in {"0", "false", "off"},
    }

    context = {
        "today_iso": timezone.localdate().isoformat(),
        "data_inicial": data_inicial_raw,
        "data_final": data_final_raw,
        "selected_sections": selected_sections,
        "report": None,
        "form_error": "",
        "observacao": observacao,
        "report_tab": report_tab,
        "programacoes_encerradas_periodos": _build_programacoes_encerradas_periodos(request),
        "can_reabrir_programacao_mes": pode_reabrir_programacao_mes(request.user),
    }

    if report_tab != "encerradas" and (data_inicial_raw or data_final_raw):
        if not data_inicial or not data_final:
            context["form_error"] = "Informe um período válido."
        elif data_inicial > data_final:
            context["form_error"] = "A data inicial não pode ser maior que a data final."
        elif not any(selected_sections.values()):
            context["form_error"] = "Selecione pelo menos uma seção para gerar o relatório."
        else:
            context["report"] = build_programacao_report(
                request=request,
                data_inicial=data_inicial,
                data_final=data_final,
                include_sections=selected_sections,
            )

    template_name = "relatorios/programacao_print.html" if is_print else "relatorios/programacao.html"
    return render(request, template_name, context)


@login_required
@require_POST
def encerrar_programacao_mes(request):
    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        return JsonResponse({"ok": False, "error": "Unidade nao definida."}, status=400)

    mes_raw = (request.POST.get("mes") or "").strip()
    try:
        mes_ref = datetime.strptime(f"{mes_raw}-01", "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse({"ok": False, "error": "Mes invalido."}, status=400)

    start, end = _month_bounds(mes_ref)
    qs = Programacao.objects.filter(unidade_id=unidade_id, data__gte=start, data__lt=end)
    total = qs.count()
    if total <= 0:
        return JsonResponse({"ok": False, "error": "Nenhuma programacao encontrada para este mes."}, status=404)

    now = timezone.now()
    meta_expediente_id = _meta_expediente_id()
    if meta_expediente_id is not None:
        ProgramacaoItem.objects.filter(programacao__in=qs, meta_id=meta_expediente_id).update(
            concluido=True,
            concluido_em=now,
            concluido_por=request.user,
            cancelada=False,
            nao_realizada_justificada=False,
        )

    itens_abertos = ProgramacaoItem.objects.filter(programacao__in=qs).filter(_itens_abertos_bloqueantes_q())
    if meta_expediente_id is not None:
        itens_abertos = itens_abertos.exclude(meta_id=meta_expediente_id)
    itens_abertos = itens_abertos.exclude(observacao__contains=ENCERRADA_AUTOMATICAMENTE_MARKER)
    origens_remarcadas_concluidas = _origens_remarcadas_concluidas_ids(itens_abertos.values_list("id", flat=True))
    if origens_remarcadas_concluidas:
        itens_abertos = itens_abertos.exclude(id__in=origens_remarcadas_concluidas)
    bloqueios = itens_abertos.aggregate(
        pendentes=Count("id", filter=Q(concluido_em__isnull=True)),
        nao_realizadas=Count("id", filter=Q(concluido_em__isnull=False)),
    )
    pendentes = int(bloqueios.get("pendentes") or 0)
    nao_realizadas = int(bloqueios.get("nao_realizadas") or 0)
    total_bloqueios = pendentes + nao_realizadas
    if total_bloqueios > 0:
        partes = []
        if pendentes:
            partes.append(f"{pendentes} pendente(s)")
        if nao_realizadas:
            partes.append(f"{nao_realizadas} nao realizada(s) ainda em aberto")
        detalhe = " e ".join(partes)
        return JsonResponse(
            {
                "ok": False,
                "error": (
                    f"Nao e possivel encerrar a programacao mensal porque ha {detalhe}. "
                    "Antes de encerrar, conclua os itens, marque como nao realizada justificada ou cancele."
                ),
                "pendentes": pendentes,
                "nao_realizadas": nao_realizadas,
            },
            status=409,
        )

    updated = qs.filter(concluida=False).update(
        concluida=True,
        concluida_em=now,
        concluida_por=request.user,
    )
    return JsonResponse({
        "ok": True,
        "mes": mes_raw,
        "total": total,
        "updated": updated,
        "message": "Programacao mensal encerrada.",
    })


@login_required
@require_POST
def reabrir_programacao_mes(request):
    if not pode_reabrir_programacao_mes(request.user):
        return JsonResponse(
            {"ok": False, "error": "Voce nao tem permissao para reabrir esta programacao mensal."},
            status=403,
        )

    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        return JsonResponse({"ok": False, "error": "Unidade nao definida."}, status=400)

    mes_raw = (request.POST.get("mes") or "").strip()
    try:
        mes_ref = datetime.strptime(f"{mes_raw}-01", "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse({"ok": False, "error": "Mes invalido."}, status=400)

    start, end = _month_bounds(mes_ref)
    qs = Programacao.objects.filter(unidade_id=unidade_id, data__gte=start, data__lt=end)
    total = qs.count()
    if total <= 0:
        return JsonResponse({"ok": False, "error": "Nenhuma programacao encontrada para este mes."}, status=404)

    updated = qs.filter(concluida=True).update(
        concluida=False,
        concluida_em=None,
        concluida_por=None,
    )
    return JsonResponse({
        "ok": True,
        "mes": mes_raw,
        "total": total,
        "updated": updated,
        "message": "Programacao mensal reaberta.",
    })
