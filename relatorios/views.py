from __future__ import annotations

from datetime import date, datetime

from django.contrib.auth.decorators import login_required
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
            pendentes=Count("id", filter=Q(concluido=False, concluido_em__isnull=True, cancelada=False, nao_realizada_justificada=False)),
        )
        row.update({key: int(value or 0) for key, value in item_counts.items()})
        solucionadas = (
            row["concluidas"]
            + row["justificadas"]
            + row["canceladas"]
            + row["nao_realizadas"]
            + row["encerradas_auto"]
        )
        row["percentual_solucionado"] = round((solucionadas / row["total_atividades"]) * 100, 1) if row["total_atividades"] else 0
        periodos.append(row)
    return periodos


def _month_bounds(mes: date) -> tuple[date, date]:
    start = mes.replace(day=1)
    if start.month == 12:
        return start, date(start.year + 1, 1, 1)
    return start, date(start.year, start.month + 1, 1)


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
