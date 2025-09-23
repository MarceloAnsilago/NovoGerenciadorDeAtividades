# programar/views.py
from __future__ import annotations

import html
import json, logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.test.client import RequestFactory
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET
from core.utils import get_unidade_atual_id
from servidores.models import Servidor
from descanso.models import Descanso
from programar.models import Programacao, ProgramacaoItem, ProgramacaoItemServidor
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseNotAllowed
from django.views.decorators.http import require_GET, require_POST
from django.utils import timezone
from metas.models import Meta
from veiculos.models import Veiculo
from metas.models import Meta
from core.utils import get_unidade_atual_id
# =============================================================================
# Página
# =============================================================================
def calendario_view(request):
    ctx = {}
    unidade_id = get_unidade_atual_id(request)
    # tenta achar a meta por título na unidade atual; se não houver, pega a primeira global
    expediente = (Meta.objects
                    .filter(titulo__iexact='Expediente Administrativo', unidade_criadora_id=unidade_id)
                    .first()
                  or Meta.objects
                    .filter(titulo__iexact='Expediente Administrativo')
                    .first())
    ctx["META_EXPEDIENTE_ID"] = expediente.id if expediente else None
    return render(request, "programar/calendario.html", ctx)


# =============================================================================
# APIs STUBS (mantêm a página funcionando enquanto migramos)
# =============================================================================
def events_feed(request):
    """Feed do calendário (no momento seguimos usando o feed do legado no front)."""
    return JsonResponse([], safe=False)


def metas_disponiveis(request):
    return JsonResponse({"metas": []})


log = logging.getLogger(__name__)

def _impedidos_por_descanso(unidade_id: int | None, data_ref):
    if not unidade_id:
        return [], set()

    qs = (
        Descanso.objects
        .select_related("servidor")
        .filter(
            servidor__unidade_id=unidade_id,
            data_inicio__lte=data_ref,
            data_fim__gte=data_ref,
        )
        .order_by("servidor_id", "-data_inicio", "-id")
    )

    impedidos_map: Dict[int, dict] = {}
    for d in qs:
        if d.servidor_id in impedidos_map:
            continue
        tipo_label = getattr(d, "get_tipo_display", lambda: "Descanso")()
        periodo = f"{d.data_inicio:%d/%m}–{d.data_fim:%d/%m}"
        motivo = f"{tipo_label} ({periodo})"
        obs = getattr(d, "observacoes", None)
        if obs:
            motivo += f" — {obs}"
        impedidos_map[d.servidor_id] = {
            "id": d.servidor_id,
            "nome": d.servidor.nome,
            "motivo": motivo,
            "origem": "descanso",
        }
    return list(impedidos_map.values()), set(impedidos_map.keys())


@require_GET
def servidores_para_data(request):
    data_str = request.GET.get("data")
    if not data_str:
        return JsonResponse({"livres": [], "impedidos": []})
    try:
        data_ref = datetime.strptime(data_str, "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse({"livres": [], "impedidos": []})

    unidade_id = get_unidade_atual_id(request)

    # 1) legado (opcional)
    livres_legacy, impedidos_legacy = [], []
    try:
        from programar_atividades import views as legacy  # type: ignore
        rf = RequestFactory()
        req = rf.get("/programar_atividades/servidores-para-data/", {"data": data_str})
        req.user = getattr(request, "user", None)
        req.session = getattr(request, "session", None)
        req._dont_enforce_csrf_checks = True  # type: ignore[attr-defined]

        resp = legacy.servidores_para_data(req)  # type: ignore[attr-defined]
        raw = getattr(resp, "content", b"").decode(getattr(resp, "charset", "utf-8")) if hasattr(resp, "content") else ""
        data = json.loads(raw) if raw.strip() else {}
        livres_legacy = data.get("livres") or []
        impedidos_legacy = data.get("impedidos") or []
    except Exception:
        log.exception("Erro ao consultar endpoint legado servidores_para_data")

    # 2) normaliza legado
    def _nome(x): return x.get("nome") or x.get("name") or x.get("servidor") or x.get("servidor_nome") or ""
    def _id(x):   return x.get("id") or x.get("servidor_id")
    def _mot(x):  return x.get("motivo") or x.get("reason") or x.get("justificativa") or ""

    impedidos_norm = []
    seen = set()
    for i in impedidos_legacy:
        sid, nm = _id(i), _nome(i)
        if sid is None and not nm:
            continue
        k = sid if sid is not None else nm
        if k in seen:
            continue
        seen.add(k)
        impedidos_norm.append({"id": sid, "nome": nm, "motivo": _mot(i)})

    # 3) descanso (unidade/data)
    impedidos_descanso, _ = _impedidos_por_descanso(unidade_id, data_ref)

    # 4) merge (prioriza descanso)
    by_key = { (i["id"] if i["id"] is not None else i["nome"]) : i for i in impedidos_norm }
    for i in impedidos_descanso:
        k = i["id"] if i["id"] is not None else i["nome"]
        by_key[k] = i
    impedidos_final = list(by_key.values())

    # 5) livres = todos da unidade - impedidos (ou legado se sem unidade)
    try:
        if unidade_id:
            ids_imp = {i["id"] for i in impedidos_final if i.get("id") is not None}
            qs = Servidor.objects.filter(unidade_id=unidade_id).order_by("nome")
            if ids_imp:
                qs = qs.exclude(id__in=ids_imp)
            livres_final = [{"id": s.id, "nome": s.nome} for s in qs]
        else:
            # sem unidade no contexto: replica livres do legado se houver
            livres_final = [{"id": i.get("id"), "nome": _nome(i)} for i in livres_legacy]
    except Exception:
        log.exception("Erro calculando 'livres'")
        livres_final = [{"id": i.get("id"), "nome": _nome(i)} for i in livres_legacy]

    return JsonResponse({"livres": livres_final, "impedidos": impedidos_final})
def _parse_date(s: str) -> date | None:
    try:
        y, m, d = map(int, s.split("-"))
        return date(y, m, d)
    except Exception:
        return None

@require_GET
def servidores_para_data(request):
    iso = request.GET.get("data")
    d = _parse_date(iso or "")
    if not d:
        return HttpResponseBadRequest("data inválida (YYYY-MM-DD)")

    unidade_id = get_unidade_atual_id(request)
    # base: todos ativos da unidade
    qs_base = Servidor.objects.filter(unidade_id=unidade_id, ativo=True).only("id","nome").order_by("nome")

    # impedidos por descanso (data dentro do intervalo)
    imp_qs = (Descanso.objects
              .select_related("servidor")
              .filter(servidor__unidade_id=unidade_id, data_inicio__lte=d, data_fim__gte=d))
    impedidos_ids = set(imp_qs.values_list("servidor_id", flat=True))

    livres = [{"id": s.id, "nome": s.nome} for s in qs_base if s.id not in impedidos_ids]
    impedidos = [{"id": r.servidor_id, "nome": r.servidor.nome, "motivo": r.tipo} for r in imp_qs]

    return JsonResponse({"livres": livres, "impedidos": impedidos})

@csrf_exempt   # ideal: usar CSRF token do template; deixe exempt se estiver testando via fetch sem token
@require_POST
def salvar_programacao(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON inválido")

    iso = payload.get("data")
    d = _parse_date(iso or "")
    if not d:
        return HttpResponseBadRequest("Campo 'data' obrigatório (YYYY-MM-DD).")

    itens = payload.get("itens", [])
    if not isinstance(itens, list):
        return HttpResponseBadRequest("Campo 'itens' deve ser uma lista.")

    unidade_id = get_unidade_atual_id(request)
    user = request.user if request.user.is_authenticated else None
    agora = timezone.now()

    prog, _created = Programacao.objects.get_or_create(
        data=d,
        unidade_id=unidade_id,
        defaults={
            "observacao": payload.get("observacao", "") or "",
            "concluida": False,
            "criado_em": agora,
            "criado_por": user,
        }
    )

    itens_criados = []
    for it in itens:
        meta_id = it.get("meta_id")
        if not meta_id:
            return HttpResponseBadRequest("Item sem 'meta_id'.")
        obs = it.get("observacao", "") or ""
        veiculo_id = it.get("veiculo_id")

        meta = Meta.objects.get(id=meta_id)
        veiculo = None
        if veiculo_id:
            veiculo = Veiculo.objects.get(id=veiculo_id)

        item = ProgramacaoItem.objects.create(
            programacao=prog,
            meta=meta,
            observacao=obs,
            concluido=False,
            criado_em=agora,
            veiculo=veiculo,
        )

        servidores_ids = it.get("servidores_ids", []) or []
        links = [
            ProgramacaoItemServidor(item=item, servidor_id=sid)
            for sid in servidores_ids
        ]
        if links:
            ProgramacaoItemServidor.objects.bulk_create(links)

        itens_criados.append({"item_id": item.id, "servidores": servidores_ids})

    return JsonResponse({
        "ok": True,
        "programacao_id": prog.id,
        "itens_criados": itens_criados
    })

@require_GET
def programacao_do_dia(request):
    iso = request.GET.get("data")
    d = _parse_date(iso or "")
    if not d:
        return HttpResponseBadRequest("data inválida")
    unidade_id = get_unidade_atual_id(request)

    try:
        prog = Programacao.objects.get(data=d, unidade_id=unidade_id)
    except Programacao.DoesNotExist:
        return JsonResponse({"itens": []})

    out = []
    for item in (ProgramacaoItem.objects
                 .select_related("meta", "veiculo")
                 .filter(programacao=prog)
                 .order_by("id")):
        srv_ids = list(ProgramacaoItemServidor.objects
                       .filter(item=item).values_list("servidor_id", flat=True))
        out.append({
            "id": item.id,
            "meta_id": item.meta_id,
            "veiculo_id": item.veiculo_id,
            "observacao": item.observacao,
            "concluido": item.concluido,
            "servidores_ids": srv_ids,
        })
    return JsonResponse({"itens": out})


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
    e retorna itens normalizados:
      { meta, servidores[nomes], servidor_ids[ids], veiculo }
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

        serv_nomes: list[str] = []
        serv_ids: list[str] = []
        for s in servidores:
            sid = s.get("id")
            if sid is not None:
                serv_ids.append(str(sid))
            nome = s.get("nome") or s.get("servidor")
            if not nome:
                nome = f"Servidor #{sid}" if sid else "Servidor"
            serv_nomes.append(nome)

        veic = it.get("veiculo_label") or it.get("veiculo") or it.get("veiculo_nome") or ""
        if not veic:
            vid = it.get("veiculo_id")
            veic = f"#{vid}" if vid else ""

        out.append({
            "meta": meta_nome,
            "servidores": serv_nomes,
            "servidor_ids": serv_ids,
            "veiculo": veic,
        })
    return out


def _fetch_expediente_admin_via_bridge(
    request,
    iso: str,
    alocados_ids: set[str],
) -> tuple[list[str], list[dict[str, str]]]:
    """
    Usa servidores_para_data (livres/impedidos) e monta:
      - expediente (nomes) = livres - alocados - impedidos
      - impedidos: lista [{nome, motivo}]
    """
    try:
        from programar_atividades import views as legacy  # type: ignore
    except Exception:
        return [], []

    rf = RequestFactory()
    req = rf.get("/programar_atividades/servidores_para_data/", {"data": iso})
    req.user = getattr(request, "user", None)
    req.session = getattr(request, "session", None)
    req._dont_enforce_csrf_checks = True  # type: ignore[attr-defined]

    try:
        resp = legacy.servidores_para_data(req)  # type: ignore[attr-defined]
        raw = getattr(resp, "content", b"").decode(getattr(resp, "charset", "utf-8")) if hasattr(resp, "content") else ""
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}

    livres = data.get("livres") or []
    impedidos = data.get("impedidos") or []

    # mapas/sets auxiliares
    livres_map: dict[str, str] = {}
    for s in livres:
        sid = str(s.get("id", "")).strip()
        if sid:
            nome = s.get("nome") or f"Servidor #{sid}"
            livres_map[sid] = nome

    impedidos_ids: set[str] = set()
    impedidos_list: list[dict[str, str]] = []
    for s in impedidos:
        sid = str(s.get("id", "")).strip()
        nome = s.get("nome") or (f"Servidor #{sid}" if sid else "Servidor")
        motivo = s.get("motivo") or "Impedido"
        impedidos_list.append({"nome": nome, "motivo": motivo})
        if sid:
            impedidos_ids.add(sid)

    # expediente = livres - alocados - impedidos
    ok_ids = (set(livres_map.keys()) - alocados_ids) - impedidos_ids
    expediente_nomes = sorted([livres_map[i] for i in ok_ids], key=str.casefold)

    return expediente_nomes, impedidos_list


def _daterange_inclusive(d0: date, d1: date):
    cur = d0
    while cur <= d1:
        yield cur
        cur += timedelta(days=1)


def _weekday_pt_short(idx: int) -> str:
    return ["seg.", "ter.", "qua.", "qui.", "sex.", "sáb.", "dom."][idx % 7]


def _render_programacao_semana_html(request, start_iso: str, end_iso: str) -> str:
    """
    Tabela por dia:
      1) Expediente administrativo (primeiro)
      2) Atividades do dia
      3) Impedidos (informativo)
    Regras:
      - Coluna Atividade centralizada (.atividade-cell)
      - Servidores de atividade: uma linha por nome + S/N
      - Servidores do expediente: inline, separados por vírgula, sem S/N
      - Coluna 'Realizada': S/N só para atividades; '—' para expediente/impedidos
    """
    ds = _parse_iso(start_iso)
    de = _parse_iso(end_iso)
    if not ds or not de:
        return "<div class='text-muted'>Intervalo inválido.</div>"

    def _srv_list_html(nomes: list[str], *, with_boxes: bool = True, inline: bool = False) -> str:
        if not nomes:
            return "<span class='text-muted'>—</span>"

        if inline or not with_boxes:
            # compacto: "ALICE, BOB, CAROL"
            return "<span class='srv-inline'>" + ", ".join(html.escape(n) for n in nomes) + "</span>"

        # padrão: uma linha por servidor com caixinhas
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

        # Atividades via bridge legado
        itens = _fetch_programacao_dia_via_bridge(request, iso)

        # ids alocados em qualquer atividade do dia
        alocados_ids: set[str] = set()
        for it in itens:
            for sid in it.get("servidor_ids", []):
                if sid:
                    alocados_ids.add(str(sid))

        # expediente (livres - alocados) e impedidos
        expediente, impedidos = _fetch_expediente_admin_via_bridge(request, iso, alocados_ids)

        # ---- ORDEM: expediente -> atividades -> impedidos ----
        blocks: list[dict] = []
        if expediente:
            blocks.append({"kind": "expediente", "servidores": expediente})
        for it in itens:
            blocks.append({
                "kind": "atividade",
                "meta": it["meta"],
                "servidores": it["servidores"],
                "veiculo": it["veiculo"],
            })
        if impedidos:
            blocks.append({"kind": "impedidos", "dados": impedidos})

        total = len(blocks)
        if total == 0:
            rows_html.append(
                "<tr>"
                f"<td class='dia-cell'>{html.escape(dia_label)}</td>"
                "<td colspan='4' class='text-muted'>Sem programação.</td>"
                "</tr>"
            )
            continue

        tem_algum = True

        for idx, b in enumerate(blocks):
            open_tr = "<tr>"
            dia_td = ""
            if idx == 0:
                dia_td = f"<td class='dia-cell' rowspan='{total}'>{html.escape(dia_label)}</td>"

            if b["kind"] == "expediente":
                rows_html.append(
                    open_tr
                    + dia_td
                    + "<td class='atividade-cell'><em>Expediente administrativo</em></td>"
                    + f"<td>{_srv_list_html(b['servidores'], with_boxes=False, inline=True)}</td>"
                    + "<td class='text-nowrap'>—</td>"
                    + "<td class='realizada-cell'>—</td>"
                    + "</tr>"
                )

            elif b["kind"] == "atividade":
                rows_html.append(
                    open_tr
                    + dia_td
                    + f"<td class='atividade-cell'>{html.escape(b['meta'])}</td>"
                    + f"<td>{_srv_list_html(b['servidores'], with_boxes=True, inline=False)}</td>"
                    + f"<td class='text-nowrap'>{html.escape(b['veiculo'])}</td>"
                    + f"<td class='realizada-cell'>{_realizada_boxes()}</td>"
                    + "</tr>"
                )

            else:  # impedidos (informativo)
                imp_lines = "".join(
                    f"<div class='text-muted'><span class='fw-semibold'>{html.escape(i['nome'])}</span>"
                    f" — {html.escape(i['motivo'])}</div>"
                    for i in b["dados"]
                )
                rows_html.append(
                    open_tr
                    + dia_td
                    + "<td class='atividade-cell'><em>Impedidos</em></td>"
                    + f"<td>{imp_lines}</td>"
                    + "<td class='text-nowrap'>—</td>"
                    + "<td class='realizada-cell'>—</td>"
                    + "</tr>"
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
