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

    template_name = "relatorios/programacao_print.html" if is_print else "relatorios/programacao.html"
    return render(request, template_name, context)
