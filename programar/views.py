# programar/views.py
from __future__ import annotations

import html
import json
from datetime import date, datetime, timedelta
from typing import Any, Dict, List

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.test.client import RequestFactory
from django.views.decorators.csrf import csrf_exempt


# =============================================================================
# Página
# =============================================================================
def calendario_view(request):
    """Página principal do app novo."""
    return render(request, "programar/calendario.html")


# =============================================================================
# APIs STUBS (mantêm a página funcionando enquanto migramos)
# =============================================================================
def events_feed(request):
    """Feed do calendário (no momento seguimos usando o feed do legado no front)."""
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


# =============================================================================
# Helpers – datas
# =============================================================================
def _parse_iso(s: str) -> date | None:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


# =============================================================================
# Helpers – PLANTONISTAS (bridge + ORM + render)
# =============================================================================
def _fetch_plantonistas_via_bridge(request, start: str, end: str) -> List[Dict[str, Any]]:
    """
    Chama plantao.views.servidores_por_intervalo com várias combinações
    de parâmetros, propagando user/session. Retorna lista de dicts.
    """
    try:
        from plantao import views as plantao_views  # type: ignore
    except Exception:
        return []

    rf = RequestFactory()

    combos = [
        {"start": start, "end": end},
        {"inicio": start, "fim": end},
        {"start": start, "end": end, "inicio": start, "fim": end},
    ]
    plantao_id = request.GET.get("plantao_id") or request.session.get("plantao_id")
    if plantao_id:
        for c in combos:
            c["plantao_id"] = plantao_id

    for params in combos:
        try:
            req = rf.get("/plantao/servidores-por-intervalo/", params)
            req.user = getattr(request, "user", None)
            req.session = getattr(request, "session", None)
            req._dont_enforce_csrf_checks = True  # type: ignore[attr-defined]

            resp = plantao_views.servidores_por_intervalo(req)  # type: ignore[attr-defined]
            raw = getattr(resp, "content", b"").decode(getattr(resp, "charset", "utf-8")) if hasattr(resp, "content") else ""
            data = json.loads(raw) if raw.strip() else {}
            servidores = data.get("servidores") if isinstance(data, dict) else None
            if isinstance(servidores, list) and servidores:
                return servidores
        except Exception:
            continue

    return []


def _fetch_plantonistas_via_orm(request, start: str, end: str) -> List[Dict[str, Any]]:
    """
    Fallback: busca direto nas tabelas do app plantao as semanas que
    intersectam o intervalo [start, end] e lista seus servidores.
    """
    ds, de = _parse_iso(start), _parse_iso(end)
    if not ds or not de:
        return []

    try:
        from plantao.models import Semana, SemanaServidor  # type: ignore

        plantao_id = request.GET.get("plantao_id") or request.session.get("plantao_id")
        qs = Semana.objects.filter(inicio__lte=de, fim__gte=ds)
        if plantao_id:
            qs = qs.filter(plantao_id=plantao_id)

        semanas = list(qs.order_by("ordem", "inicio"))
        if not semanas:
            return []

        out: List[Dict[str, Any]] = []
        for sem in semanas:
            ss_qs = (
                SemanaServidor.objects.filter(semana=sem)
                .select_related("servidor")
                .order_by("ordem", "servidor__nome")
            )
            for ss in ss_qs:
                nome = getattr(getattr(ss, "servidor", None), "nome", "") or ""
                tel = getattr(ss, "telefone_snapshot", "") or ""
                out.append({"nome": nome, "telefone": tel})
        return out
    except Exception:
        return []


def _render_plantonistas_html(servidores: List[Dict[str, Any]], start: str, end: str) -> str:
    esc = lambda s: html.escape(str(s or ""))
    header = (
        '<h6 class="fw-semibold mb-2">'
        '<span class="badge bg-light border me-2">'
        '<i class="bi bi-person-badge text-primary"></i></span>'
        f'Plantonista(s) da semana <small class="text-muted">({esc(start)} → {esc(end)})</small>'
        "</h6>"
    )
    if not servidores:
        return header + '<div class="text-muted">Nenhum plantonista encontrado para o período.</div>'

    items = []
    for s in servidores:
        nome = esc(s.get("nome") or s.get("servidor") or "")
        tel = s.get("telefone")
        tel_html = f' <span class="text-muted">— ({esc(tel)})</span>' if tel else ""
        items.append(f"<li>{nome}{tel_html}</li>")

    return header + f'<ul class="mb-0">{"".join(items)}</ul>'


# =============================================================================
# Helpers – PROGRAMAÇÃO DA SEMANA (bridge no legado) + render
# =============================================================================
def _fetch_programacao_dia_via_bridge(request, iso: str) -> list[dict[str, Any]]:
    """
    Chama programar_atividades.views.programacao_do_dia(data=YYYY-MM-DD)
    e retorna itens normalizados [{meta, servidores:[...], veiculo}].
    """
    try:
        from programar_atividades import views as legacy  # type: ignore
    except Exception:
        return []

    rf = RequestFactory()
    req = rf.get("/programar_atividades/programacao_do_dia/", {"data": iso})
    req.user = getattr(request, "user", None)
    req.session = getattr(request, "session", None)
    req._dont_enforce_csrf_checks = True  # type: ignore[attr-defined]

    try:
        resp = legacy.programacao_do_dia(req)  # type: ignore[attr-defined]
        raw = getattr(resp, "content", b"").decode(getattr(resp, "charset", "utf-8")) if hasattr(resp, "content") else ""
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        return []

    prog = (data or {}).get("programacao") or {}
    itens = prog.get("itens") or []

    out: list[dict[str, Any]] = []
    for it in itens:
        meta_nome = it.get("meta_nome") or it.get("meta") or f"Atividade #{it.get('meta_id','')}".strip()
        servidores = it.get("servidores") or []
        serv_nomes = []
        for s in servidores:
            nome = s.get("nome") or s.get("servidor")
            if not nome:
                sid = s.get("id")
                nome = f"Servidor #{sid}" if sid else "Servidor"
            serv_nomes.append(nome)
        veic = it.get("veiculo_label") or it.get("veiculo") or it.get("veiculo_nome") or ""
        if not veic:
            vid = it.get("veiculo_id")
            veic = f"#{vid}" if vid else ""
        out.append({"meta": meta_nome, "servidores": serv_nomes, "veiculo": veic})
    return out


def _daterange_inclusive(d0: date, d1: date):
    cur = d0
    while cur <= d1:
        yield cur
        cur += timedelta(days=1)


def _weekday_pt_short(idx: int) -> str:
    return ["seg.", "ter.", "qua.", "qui.", "sex.", "sáb.", "dom."][idx % 7]


def _render_programacao_semana_html(request, start_iso: str, end_iso: str) -> str:
    """
    Monta tabela por dia com:
      - atividade
      - servidores (cada nome com S/N alinhado à direita da célula)
      - veículo
      - coluna 'Realizada' com S/N alinhado à direita
    """
    ds = _parse_iso(start_iso)
    de = _parse_iso(end_iso)
    if not ds or not de:
        return "<div class='text-muted'>Intervalo inválido.</div>"

    def _srv_list_html(nomes: list[str]) -> str:
        if not nomes:
            return "<span class='text-muted'>—</span>"
        parts = []
        for nm in nomes:
            safe = html.escape(nm)
            parts.append(
                "<div class='srv-line'>"
                f"<span class='srv-name'>{safe}</span>"
                "<span class='srv-choices'>"
                "<span class='print-cbx'></span><small>S</small>"
                "<span class='print-cbx'></span><small>N</small>"
                "</span>"
                "</div>"
            )
        return "".join(parts)

    def _realizada_boxes() -> str:
        return (
            "<div class='choice'>"
            "<span class='print-cbx'></span><small>Sim</small>"
            "<span class='print-cbx'></span><small>Não</small>"
            "</div>"
        )

    rows_html: list[str] = []
    tem_algum = False

    for dt in _daterange_inclusive(ds, de):
        iso = dt.strftime("%Y-%m-%d")
        dia_label = f"{dt.strftime('%d/%m')} ({_weekday_pt_short(dt.weekday())})"
        itens = _fetch_programacao_dia_via_bridge(request, iso)

        if not itens:
            rows_html.append(
                "<tr>"
                f"<td class='dia-cell'>{html.escape(dia_label)}</td>"
                "<td colspan='4' class='text-muted'>Sem programação.</td>"
                "</tr>"
            )
            continue

        tem_algum = True

        # primeira linha do dia (com rowspan na coluna "Dia")
        first = itens[0]
        rows_html.append(
            "<tr>"
            f"<td class='dia-cell' rowspan='{len(itens)}'>{html.escape(dia_label)}</td>"
            f"<td>{html.escape(first['meta'])}</td>"
            f"<td>{_srv_list_html(first['servidores'])}</td>"
            f"<td class='text-nowrap'>{html.escape(first['veiculo'])}</td>"
            f"<td class='realizada-cell'>{_realizada_boxes()}</td>"
            "</tr>"
        )

        # demais linhas do mesmo dia (sem a coluna "Dia")
        for it in itens[1:]:
            rows_html.append(
                "<tr>"
                f"<td>{html.escape(it['meta'])}</td>"
                f"<td>{_srv_list_html(it['servidores'])}</td>"
                f"<td class='text-nowrap'>{html.escape(it['veiculo'])}</td>"
                f"<td class='realizada-cell'>{_realizada_boxes()}</td>"
                "</tr>"
            )

    table = (
        "<div class='mt-3'>"
        "<h6 class='fw-semibold mb-2'><i class='bi bi-table me-1'></i> Programação da semana</h6>"
        "<div class='table-responsive'>"
        "<table class='table table-sm align-middle mb-0 programacao-semana-table'>"
        "<thead class='table-light'>"
        "<tr>"
        "<th style='width:110px'>Dia</th>"
        "<th>Atividade</th>"
        "<th>Servidores</th>"
        "<th style='width:200px'>Veículo</th>"
        "<th style='width:140px'>Realizada</th>"
        "</tr>"
        "</thead><tbody>"
        + "".join(rows_html) +
        "</tbody></table></div>"
        + ("" if tem_algum else "<div class='text-muted mt-2'>Nenhuma atividade nesta semana.</div>")
        + "</div>"
    )
    return table



# =============================================================================
# Relatórios (JSON + Imprimível)
# =============================================================================
def relatorios_parcial(request):
    start = request.GET.get("start", "")
    end = request.GET.get("end", "")

    servidores = _fetch_plantonistas_via_bridge(request, start, end)
    if not servidores:
        servidores = _fetch_plantonistas_via_orm(request, start, end)

    plantonistas_html = _render_plantonistas_html(servidores, start, end)
    tabela_semana_html = _render_programacao_semana_html(request, start, end)

    html_out = f"""
    <div id="relatorioPrintArea" class="card border-0 shadow-sm">
      <div class="card-body">
        <h5 class="card-title mb-2">Relatório (parcial)</h5>
        <div class="text-muted mb-3">Período: <strong>{html.escape(start)} → {html.escape(end)}</strong></div>
        <div class="mb-3">{plantonistas_html}</div>
        <hr class="my-3">
        {tabela_semana_html}
      </div>
    </div>
    """
    return JsonResponse({"ok": True, "html": html_out})


def print_relatorio_semana(request):
    start = request.GET.get("start", "")
    end = request.GET.get("end", "")

    servidores = _fetch_plantonistas_via_bridge(request, start, end)
    if not servidores:
        servidores = _fetch_plantonistas_via_orm(request, start, end)

    plantonistas_html = _render_plantonistas_html(servidores, start, end)
    tabela_semana_html = _render_programacao_semana_html(request, start, end)

    html_out = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Relatório {html.escape(start)} → {html.escape(end)}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body{{padding:16px}}
    @page{{ margin:12mm; }}
    .table td,.table th{{ vertical-align: top; }}
    @media print{{ .no-print{{display:none!important}} }}
  </style>
</head>
<body>
  <div class="container">
    <div class="d-flex align-items-center justify-content-between no-print mb-3">
      <h3 class="mb-0">Relatório semanal</h3>
      <button class="btn btn-sm btn-outline-secondary" onclick="window.print()">Imprimir</button>
    </div>
    <div class="text-muted mb-3">Período: <strong>{html.escape(start)} → {html.escape(end)}</strong></div>
    <div class="mb-3">{plantonistas_html}</div>
    <hr class="my-3">
    {tabela_semana_html}
  </div>
</body>
</html>"""
    return HttpResponse(html_out)


# (Opcional) endpoint dummy para manter compatibilidade em dev
def servidores_por_intervalo(request):
    return JsonResponse({"ok": True, "servidores": []})
