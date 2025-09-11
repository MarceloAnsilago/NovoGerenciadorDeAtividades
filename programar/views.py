from __future__ import annotations
import json, html
from datetime import datetime, date
from typing import List, Dict, Any

from django.http import JsonResponse, HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.test.client import RequestFactory
from django.db import connection

# === Páginas ===
def calendario_view(request):
    return render(request, "programar/calendario.html")


# === APIs “stub” para manter a página funcionando ===
def events_feed(request):
    # FullCalendar feed (vazio por enquanto – seguimos usando o feed do legado no front)
    return JsonResponse([], safe=False)

def metas_disponiveis(request):
    return JsonResponse({"metas": []})

def servidores_para_data(request):
    return JsonResponse({"livres": [], "impedidos": []})

@csrf_exempt
def salvar_programacao(request):
    return JsonResponse({"ok": True, "itens": 0, "servidores_vinculados": 0})

def programacao_do_dia(request):
    return JsonResponse({"ok": True, "programacao": None})

@csrf_exempt
def excluir_programacao(request):
    return JsonResponse({"ok": True})


# ========== RELATÓRIO (com Plantonista da Semana) ==========

def _fetch_plantonistas_via_bridge(request, start: str, end: str) -> List[Dict[str, Any]]:
    """
    Tenta chamar a view do app `plantao` diretamente (sem HTTP externo),
    repassando usuário/sessão. Retorna uma lista de servidores.
    Estrutura esperada (tolerante):
      { "ok": true, "servidores": [ { "nome": "...", "telefone": "..." }, ... ] }
    """
    try:
        # import tardio para não acoplar o app no startup caso não exista
        from plantao import views as plantao_views  # type: ignore
    except Exception:
        return []

    rf = RequestFactory()
    req_bridge = rf.get("/plantao/servidores-por-intervalo/", {"start": start, "end": end})
    # propaga contexto
    req_bridge.user = getattr(request, "user", None)
    req_bridge.session = getattr(request, "session", None)
    # evitamos CSRF nesse GET
    req_bridge._dont_enforce_csrf_checks = True  # pylint: disable=protected-access

    try:
        resp = plantao_views.servidores_por_intervalo(req_bridge)  # type: ignore[attr-defined]
    except Exception:
        return []

    try:
        # pode vir JsonResponse ou HttpResponse comum com JSON
        raw = resp.content.decode(resp.charset or "utf-8") if hasattr(resp, "content") else ""
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}

    servidores = data.get("servidores") if isinstance(data, dict) else None
    if not isinstance(servidores, list):
        return []
    return servidores


def _render_plantonistas_html(servidores: List[Dict[str, Any]], start: str, end: str) -> str:
    esc = lambda s: html.escape(str(s or ""))
    header = (
        '<h6 class="fw-semibold mb-2">'
        '<span class="badge bg-light border me-2">'
        '<i class="bi bi-person-badge text-primary"></i></span>'
        f'Plantonista(s) da semana <small class="text-muted">({esc(start)} → {esc(end)})</small>'
        '</h6>'
    )
    if not servidores:
        return header + '<div class="text-muted">Nenhum plantonista encontrado para o período.</div>'

    items = []
    for s in servidores:
        nome = esc(s.get("nome") or s.get("servidor") or "")
        tel = s.get("telefone")
        tel_html = f' <span class="text-muted">— ({esc(tel)})</span>' if tel else ""
        items.append(f"<li>{nome}{tel_html}</li>")

    return header + f'<ul class="mb-0">{ "".join(items) }</ul>'

def _parse_iso(d: str) -> date | None:
    try:
        return datetime.strptime(d, "%Y-%m-%d").date()
    except Exception:
        return None
    
def _fetch_plantonistas_via_bridge(request, start: str, end: str) -> List[Dict[str, Any]]:
    """
    Chama a view `plantao.servidores_por_intervalo` com várias combinações de parâmetros.
    Retorna lista de dicts: {nome, telefone?}
    """
    try:
        from plantao import views as plantao_views  # type: ignore
    except Exception:
        return []

    rf = RequestFactory()

    # tenta várias combinações de parâmetros aceitos
    combos = [
        {"start": start, "end": end},
        {"inicio": start, "fim": end},
        {"start": start, "end": end, "inicio": start, "fim": end},  # redundante mas inofensivo
    ]
    # propaga possível plantao_id se vier do front (ou sessão)
    plantao_id = request.GET.get("plantao_id") or request.session.get("plantao_id")
    if plantao_id:
        for c in combos:
            c["plantao_id"] = plantao_id

    for params in combos:
        try:
            req_bridge = rf.get("/plantao/servidores-por-intervalo/", params)
            req_bridge.user = getattr(request, "user", None)
            req_bridge.session = getattr(request, "session", None)
            req_bridge._dont_enforce_csrf_checks = True  # type: ignore[attr-defined]
            resp = plantao_views.servidores_por_intervalo(req_bridge)  # type: ignore[attr-defined]

            raw = getattr(resp, "content", b"").decode(getattr(resp, "charset", "utf-8")) if hasattr(resp, "content") else ""
            data = json.loads(raw) if raw.strip() else {}
            servidores = data.get("servidores") if isinstance(data, dict) else None
            if isinstance(servidores, list) and servidores:
                return servidores
        except Exception:
            # tenta próxima combinação
            continue

    return []

def relatorios_parcial(request):
    start = request.GET.get("start", "")
    end = request.GET.get("end", "")

    servidores = _fetch_plantonistas_via_bridge(request, start, end)
    if not servidores:
        servidores = _fetch_plantonistas_via_orm(request, start, end)

    plantonistas_html = _render_plantonistas_html(servidores, start, end)

    html_out = f"""
    <div id="relatorioPrintArea" class="card border-0 shadow-sm">
      <div class="card-body">
        <h5 class="card-title mb-2">Relatório (parcial)</h5>
        <div class="text-muted mb-3">Período: <strong>{html.escape(start)} → {html.escape(end)}</strong></div>
        <div class="mb-3">{plantonistas_html}</div>
        <hr class="my-3">
        <div class="text-muted"><small>Conteúdo das atividades entrará nas próximas etapas.</small></div>
      </div>
    </div>
    """
    return JsonResponse({"ok": True, "html": html_out})

def print_relatorio_semana(request):
    """
    Página imprimível (HTML completo) com a mesma seção de plantonistas.
    """
    start = request.GET.get("start", "")
    end = request.GET.get("end", "")
    servidores = _fetch_plantonistas_via_bridge(request, start, end)
    plantonistas_html = _render_plantonistas_html(servidores, start, end)

    html_out = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Relatório {html.escape(start)} → {html.escape(end)}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body{{padding:16px}}
    @media print {{
      .no-print {{ display:none !important; }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="d-flex align-items-center justify-content-between no-print mb-3">
      <h3 class="mb-0">Relatório semanal</h3>
      <button class="btn btn-sm btn-outline-secondary" onclick="window.print()">Imprimir</button>
    </div>

    <div class="text-muted mb-3">Período: <strong>{html.escape(start)} → {html.escape(end)}</strong></div>

    <div class="mb-3">
      {plantonistas_html}
    </div>

    <hr class="my-3">

    <div class="alert alert-light border">
      Conteúdo real das atividades será migrado aqui nas próximas etapas.
    </div>
  </div>
</body>
</html>"""
    return HttpResponse(html_out)


# (opcional) se seu urls.py expõe isso:
def servidores_por_intervalo(request):
    return JsonResponse({"ok": True, "servidores": []})


def _fetch_plantonistas_via_orm(request, start: str, end: str) -> List[Dict[str, Any]]:
    """
    Fallback: busca diretamente nas tabelas do app plantao as semanas que INTERSECTAM
    o intervalo [start, end] e lista os servidores daquela(s) semana(s).
    """
    ds, de = _parse_iso(start), _parse_iso(end)
    if not ds or not de:
        return []

    try:
        # Imports tardios para não acoplar forte
        from plantao.models import Semana, SemanaServidor  # type: ignore
        # se existir filtro por plantao_id, aplique
        plantao_id = request.GET.get("plantao_id") or request.session.get("plantao_id")

        semana_qs = Semana.objects.filter(inicio__lte=de, fim__gte=ds)
        if plantao_id:
            semana_qs = semana_qs.filter(plantao_id=plantao_id)

        sems = list(semana_qs.order_by("ordem", "inicio"))
        if not sems:
            return []

        out: List[Dict[str, Any]] = []
        for sem in sems:
            ss_qs = (SemanaServidor.objects
                     .filter(semana=sem)
                     .select_related("servidor")
                     .order_by("ordem", "servidor__nome"))
            for ss in ss_qs:
                nome = getattr(getattr(ss, "servidor", None), "nome", None) or ""
                tel  = getattr(ss, "telefone_snapshot", None) or ""
                out.append({"nome": nome, "telefone": tel})
        return out

    except Exception:
        # se não conseguir via ORM (models ausentes / nomes diferentes), retorna vazio
        return []
