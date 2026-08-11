from __future__ import annotations

from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .services.programacao_report_service import build_programacao_report


def _parse_date(value: str):
    try:
        return datetime.strptime(str(value or "").strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def _filter_encerradas_report(report):
    if not report:
        return report

    desempenho = report.get("desempenho")
    if not desempenho:
        return report

    rows = [
        row for row in desempenho.get("rows", [])
        if str(row.get("status_final") or "") == "encerrada_automaticamente"
    ]
    resumo = []
    for row in desempenho.get("resumo_por_atividade", []):
        encerradas = int(row.get("encerrada_automaticamente") or 0)
        if encerradas:
            item = dict(row)
            item["total_periodo"] = encerradas
            item["total_atual"] = encerradas
            item["total_execucao"] = 0
            item["cancelada_ou_removida"] = 0
            item["executada"] = 0
            item["remarcada_concluida"] = 0
            item["nao_realizada"] = 0
            item["nao_realizada_justificada"] = 0
            item["pendente"] = 0
            item["execucao_percent"] = None
            item["execucao_percent_label"] = "-"
            resumo.append(item)

    counters = {key: 0 for key in (desempenho.get("counters") or {}).keys()}
    counters["encerrada_automaticamente"] = len(rows)
    report = dict(report)
    report["desempenho"] = {
        **desempenho,
        "rows": rows,
        "total": len(rows),
        "counters": counters,
        "resumo_por_atividade": resumo,
        "nao_realizadas_grupos": [],
    }
    report["indicadores"] = {
        "cards": [
            {
                "label": "Programacoes encerradas",
                "value": len(rows),
            }
        ]
    } if report.get("indicadores") is not None else None
    return report


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
    if report_tab == "encerradas":
        selected_sections["historico"] = False
        selected_sections["desempenho"] = True
        selected_sections["indicadores"] = True

    context = {
        "today_iso": timezone.localdate().isoformat(),
        "data_inicial": data_inicial_raw,
        "data_final": data_final_raw,
        "selected_sections": selected_sections,
        "report": None,
        "form_error": "",
        "observacao": observacao,
        "report_tab": report_tab,
    }

    if data_inicial_raw or data_final_raw:
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
            if report_tab == "encerradas":
                context["report"] = _filter_encerradas_report(context["report"])

    template_name = "relatorios/programacao_print.html" if is_print else "relatorios/programacao.html"
    return render(request, template_name, context)
