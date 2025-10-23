# programar/views.py
from __future__ import annotations

import html
import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.test.client import RequestFactory
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET
from django.contrib.auth.decorators import login_required
from core.utils import get_unidade_atual_id
from servidores.models import Servidor
from descanso.models import Descanso
from programar.models import Programacao, ProgramacaoItem, ProgramacaoItemServidor
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseNotAllowed
from django.views.decorators.http import require_GET, require_POST
from django.utils import timezone
from metas.models import Meta, MetaAlocacao
from veiculos.models import Veiculo
from django.db.models import Sum
from django.db import transaction
# =============================================================================
# Página
# =============================================================================
def calendario_view(request):
    meta_expediente_id = getattr(settings, "META_EXPEDIENTE_ID", None)
    veiculos_json = "[]"
    try:
        unidade_id = get_unidade_atual_id(request)
        if unidade_id:
            veiculos_qs = (
                Veiculo.objects.filter(unidade_id=unidade_id, ativo=True)
                .order_by("nome")
                .values("id", "nome", "placa")
            )
            veiculos_json = json.dumps(list(veiculos_qs))
    except Exception:
        veiculos_json = "[]"
    return render(request, "programar/calendario.html", {
        "META_EXPEDIENTE_ID": meta_expediente_id,
        "VEICULOS_ATIVOS_JSON": veiculos_json,
    })


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

@login_required
@csrf_protect
@require_POST
def salvar_programacao(request):
    """
    Upsert de Programacao + ProgramacaoItem + ProgramacaoItemServidor,
    e remoção dos itens que não vierem no payload (delete-orphans).

    Payload esperado:
      {
        data: "YYYY-MM-DD",
        observacao: "",
        itens: [
          { id?, meta_id, observacao, veiculo_id?, servidores_ids: [int,...] },
          ...
        ]
      }
    """
    try:
        body = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "JSON inválido."}, status=400)

    iso = body.get("data")
    itens_in = body.get("itens") or []
    if not iso:
        return JsonResponse({"ok": False, "error": "Data ausente."}, status=400)

    unidade_id = get_unidade_atual_id(request)

    with transaction.atomic():
        prog, _ = Programacao.objects.get_or_create(
            data=iso,
            unidade_id=unidade_id,
            defaults={
                "observacao": body.get("observacao") or "",
                "criado_por": getattr(request, "user", None),
            },
        )

        if body.get("observacao") is not None:
            Programacao.objects.filter(pk=prog.pk).update(
                observacao=body.get("observacao") or ""
            )

        # itens já existentes
        existentes = {
            pi.id: pi
            for pi in ProgramacaoItem.objects.filter(programacao=prog).select_related("programacao")
        }
        ids_payload = set()
        total_vinculos = 0

        for it in itens_in:
            item_id = it.get("id")
            meta_id = it.get("meta_id")
            obs = it.get("observacao") or ""
            veiculo_id = it.get("veiculo_id")
            servidores_ids = list({int(s) for s in (it.get("servidores_ids") or [])})

            if not meta_id:
                continue

            # 🚩 caso especial: Expediente Administrativo
            if int(meta_id) == settings.META_EXPEDIENTE_ID:
                if item_id and item_id in existentes:
                    pi = existentes[item_id]
                    ProgramacaoItem.objects.filter(pk=pi.pk).update(
                        meta_id=settings.META_EXPEDIENTE_ID,
                        observacao=obs,
                        veiculo_id=veiculo_id,
                    )
                else:
                    pi = ProgramacaoItem.objects.create(
                        programacao=prog,
                        meta_id=settings.META_EXPEDIENTE_ID,
                        observacao=obs,
                        veiculo_id=veiculo_id,
                        concluido=False,
                    )
                    item_id = pi.id
            else:
                # fluxo normal
                if item_id and item_id in existentes:
                    pi = existentes[item_id]
                    ProgramacaoItem.objects.filter(pk=pi.pk).update(
                        meta_id=meta_id,
                        observacao=obs,
                        veiculo_id=veiculo_id,
                    )
                else:
                    pi = ProgramacaoItem.objects.create(
                        programacao=prog,
                        meta_id=meta_id,
                        observacao=obs,
                        veiculo_id=veiculo_id,
                        concluido=False,
                    )
                    item_id = pi.id

            ids_payload.add(item_id)

            # substitui vínculos de servidores
            ProgramacaoItemServidor.objects.filter(item_id=item_id).delete()
            if servidores_ids:
                bulk = [
                    ProgramacaoItemServidor(item_id=item_id, servidor_id=sid)
                    for sid in servidores_ids
                ]
                ProgramacaoItemServidor.objects.bulk_create(bulk)
                total_vinculos += len(bulk)

        # delete-orphans: remove itens que não vieram no payload
        orfaos = [pi_id for pi_id in existentes.keys() if pi_id not in ids_payload]
        if orfaos:
            ProgramacaoItemServidor.objects.filter(item_id__in=orfaos).delete()
            ProgramacaoItem.objects.filter(id__in=orfaos).delete()

    return JsonResponse({
        "ok": True,
        "programacao_id": prog.id,
        "itens": len(ids_payload),
        "servidores_vinculados": total_vinculos,
    })

@require_GET
def programacao_do_dia(request):
    """
    Bridge para programar_atividades.programacao_do_dia.
    Normaliza para o front:
      { ok, itens: [ {id?, meta_id, observacao, veiculo_id, servidores_ids[], titulo?} ] }
    Se meta_id == META_EXPEDIENTE_ID → insere título fixo "Expediente administrativo".
    """
    iso = request.GET.get("data")
    if not iso:
        return JsonResponse({"ok": True, "itens": []})

    try:
        from programar_atividades import views as legacy  # type: ignore
    except Exception:
        return JsonResponse({"ok": True, "itens": []})

    rf = RequestFactory()
    req = rf.get("/programar_atividades/programacao_do_dia/", {"data": iso})
    req.user = getattr(request, "user", None)
    req.session = getattr(request, "session", None)
    req._dont_enforce_csrf_checks = True  # type: ignore[attr-defined]

    try:
        resp = legacy.programacao_do_dia(req)  # type: ignore[attr-defined]
        raw = getattr(resp, "content", b"").decode(
            getattr(resp, "charset", "utf-8")
        ) if hasattr(resp, "content") else ""
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        return JsonResponse({"ok": True, "itens": []})

    prog = (data or {}).get("programacao") or {}
    itens_legacy = prog.get("itens") or []

    itens = []
    for it in itens_legacy:
        meta_id = it.get("meta_id")

        obj = {
            "id": it.get("id"),
            "meta_id": meta_id,
            "observacao": it.get("observacao") or "",
            "veiculo_id": it.get("veiculo_id"),
            "servidores_ids": [
                s.get("id") for s in (it.get("servidores") or []) if s.get("id") is not None
            ],
        }

        # 🚩 tratamento especial Expediente Administrativo
        if meta_id == settings.META_EXPEDIENTE_ID:
            obj["titulo"] = "Expediente administrativo"

        itens.append(obj)

    return JsonResponse({"ok": True, "itens": itens})
# antigo dummy de exclusão removido (substituído por excluir_programacao_secure)
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
      - Linha divisória mais forte entre dias (tr.day-end + td.dia-cell.day-end)
      - Coluna 'Veículo' centralizada (horizontal e vertical)
      - Ao final: Relatório de atividades por servidor (2 linhas por atividade)
    """
    ds = _parse_iso(start_iso)
    de = _parse_iso(end_iso)
    if not ds or not de:
        return "<div class='text-muted'>Intervalo inválido.</div>"

    def _srv_list_html(nomes: list[str], *, with_boxes: bool = True, inline: bool = False) -> str:
        if not nomes:
            return "<span class='text-muted'>—</span>"
        if inline or not with_boxes:
            return "<span class='srv-inline'>" + ", ".join(html.escape(n) for n in nomes) + "</span>"
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

    # ------- acumulador para o relatório por servidor (exclui expediente e impedidos)
    from collections import defaultdict
    atividades_por_servidor = defaultdict(list)  # nome -> list[ dict(dia_label, iso, atividade, veiculo) ]

    for dt in _daterange_inclusive(ds, de):
        iso = dt.strftime("%Y-%m-%d")
        dia_label = f"{dt.strftime('%d/%m')} ({_weekday_pt_short(dt.weekday())})"

        itens = _fetch_programacao_dia_via_bridge(request, iso)

        alocados_ids: set[str] = set()
        for it in itens:
            for sid in it.get("servidor_ids", []):
                if sid:
                    alocados_ids.add(str(sid))

        expediente, impedidos = _fetch_expediente_admin_via_bridge(request, iso, alocados_ids)

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
                "<tr class='day-end'>"
                f"<td class='dia-cell day-end'>{html.escape(dia_label)}</td>"
                "<td colspan='4' class='text-muted'>Sem programação.</td>"
                "</tr>"
            )
            continue

        tem_algum = True

        for idx, b in enumerate(blocks):
            is_last = (idx == total - 1)
            tr_class = "day-end" if is_last else ""
            open_tr = f"<tr class='{tr_class}'>"
            dia_td = ""
            if idx == 0:
                dia_td = f"<td class='dia-cell day-end' rowspan='{total}'>{html.escape(dia_label)}</td>"

            if b["kind"] == "expediente":
                rows_html.append(
                    open_tr
                    + dia_td
                    + "<td class='atividade-cell'><em>Expediente administrativo</em></td>"
                    + f"<td>{_srv_list_html(b['servidores'], with_boxes=False, inline=True)}</td>"
                    + "<td class='veiculo-cell text-nowrap'>—</td>"
                    + "<td class='realizada-cell'>—</td>"
                    + "</tr>"
                )
            elif b["kind"] == "atividade":
                # ---- acumula por servidor para o relatório de atividades
                for nome in (b.get("servidores") or []):
                    if nome and isinstance(nome, str):
                        atividades_por_servidor[nome].append({
                            "dia_label": dia_label,
                            "iso": iso,
                            "atividade": b["meta"],
                            "veiculo": b["veiculo"],
                        })

                rows_html.append(
                    open_tr
                    + dia_td
                    + f"<td class='atividade-cell'>{html.escape(b['meta'])}</td>"
                    + f"<td>{_srv_list_html(b['servidores'], with_boxes=True, inline=False)}</td>"
                    + f"<td class='veiculo-cell text-nowrap'>{html.escape(b['veiculo'])}</td>"
                    + f"<td class='realizada-cell'>{_realizada_boxes()}</td>"
                    + "</tr>"
                )
            else:  # impedidos
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
                    + "<td class='veiculo-cell text-nowrap'>—</td>"
                    + "<td class='realizada-cell'>—</td>"
                    + "</tr>"
                )

    # ---------- CSS embutido (pode mover p/ estático)
    style = (
        "<style>"
        "/* Veículo: centro horiz/vert */"
        ".programacao-semana-table tbody td.veiculo-cell{"
        "  text-align:center !important; vertical-align:middle !important;"
        "}"
        "/* Borda forte no fim de cada dia */"
        ".programacao-semana-table tbody tr.day-end > td,"
        ".programacao-semana-table tbody td.dia-cell.day-end{"
        "  border-bottom: 2px solid #000 !important;"
        "}"
        ".programacao-semana-table th:first-child, .programacao-semana-table td.dia-cell{ min-width:110px; }"
        ".programacao-semana-table td, .programacao-semana-table th{ vertical-align: top; }"
        "/* Mini-tabela do relatório de atividades */"
        ".rel-atividades .card-ativ{ page-break-inside: avoid; }"
        ".rel-atividades .mini-table{ width:100%; border-collapse:collapse; }"
        ".rel-atividades .mini-table td{ border:1px solid var(--bs-border-color); padding:.35rem .5rem; }"
        ".rel-atividades .mini-table .lbl{ width:180px; white-space:nowrap; }"
        ".rel-atividades .mini-table .just{ height:2.2rem; }"
        ".rel-atividades .servidor-title{ font-weight:600; margin-bottom:.35rem; }"
        "</style>"
    )

    # ---------- bloco principal (programação da semana)
    bloco_programacao = (
        "<div id='programar-programacao-semana-block' class='mt-3'>"
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

    # -------- RELATÓRIO DE ATIVIDADES (embaixo)
    # ordena servidores alfabeticamente
    servidores_ordenados = sorted(atividades_por_servidor.keys(), key=str.casefold)

    cards: list[str] = []
    for nome in servidores_ordenados:
        itens = atividades_por_servidor[nome]
        if not itens:
            continue
        # um card/“tabelinha” por servidor
        linhas = []
        # opcional: ordena por data
        itens_sorted = sorted(itens, key=lambda x: (x["iso"], x["atividade"]))
        for it in itens_sorted:
            dia = html.escape(it["dia_label"])
            iso = html.escape(it["iso"])
            atividade = html.escape(it.get("atividade") or "")

            # 1ª linha: dia do mês + semana + atividade
            linhas.append(
                "<tr>"
                "<td class='lbl'>Dia</td>"
                f"<td>{dia}" + (f": {atividade}" if atividade else "") + "</td>"
                "</tr>"
            )

            # 2ª linha: data marcada + linha para justificativa
            linhas.append(
                "<tr>"
                "<td class='lbl'>Data marcada</td>"
                f"<td>{iso} — <span class='text-muted'>Justificativa:</span> "
                "<span class='just d-inline-block' style='display:inline-block;border-bottom:1px solid var(--bs-border-color);width:70%;'></span>"
                "</td>"
                "</tr>"
            )
        card = (
            "<div class='card card-ativ border-0 shadow-sm mb-3 rel-atividades'>"
            "<div class='card-body p-3'>"
            f"<div class='servidor-title'><i class='bi bi-person me-1'></i>Servidor: {html.escape(nome)}</div>"
            "<table class='mini-table'>"
            "<tbody>"
            + "".join(linhas) +
            "</tbody></table>"
            "</div>"
            "</div>"
        )
        cards.append(card)

    bloco_atividades = (
        "<div class='mt-4 rel-atividades'>"
        "<h6 class='fw-semibold mb-2'><i class='bi bi-list-check me-1'></i> Justificativa de atividades não realizadas</h6>"
        + ("".join(cards) if cards else "<div class='text-muted'>Nenhuma atividade para os servidores no período.</div>")
        + "</div>"
    )

    # retorna tudo: programação + rel. atividades
    return style + bloco_programacao + bloco_atividades



# =============================================================================
# Relatórios (JSON + Imprimível)
# =============================================================================
@login_required
@require_GET
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


@login_required
@require_GET
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


@login_required
@require_GET
def events_feed(request):
    """Feed para FullCalendar: Programacao como eventos all-day no intervalo."""
    start = request.GET.get("start")
    end = request.GET.get("end")
    start_date = _parse_iso(start[:10]) if start else None
    end_date = _parse_iso(end[:10]) if end else None

    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        return JsonResponse([], safe=False)

    qs = Programacao.objects.filter(unidade_id=unidade_id)
    if start_date:
        qs = qs.filter(data__gte=start_date)
    if end_date:
        qs = qs.filter(data__lte=end_date)

    data = []
    for prog in qs:
        qtd_itens = ProgramacaoItem.objects.filter(programacao_id=prog.id).count()
        title = f"({qtd_itens} atividade{'s' if qtd_itens != 1 else ''})"
        if getattr(prog, 'concluida', False):
            title = "[Concluída] " + title
        data.append({"id": prog.id, "title": title, "start": prog.data.isoformat(), "allDay": True})
    return JsonResponse(data, safe=False)


@login_required
@require_GET
def metas_disponiveis(request):
    """Metas alocadas para a UNIDADE atual (com somas alocado/executado)."""
    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        return JsonResponse({"metas": []})

    atividade_id = request.GET.get("atividade")
    qs = MetaAlocacao.objects.select_related("meta", "meta__atividade").filter(unidade_id=unidade_id)
    if atividade_id:
        qs = qs.filter(meta__atividade_id=atividade_id)

    bucket: Dict[int, Dict[str, Any]] = {}
    for al in qs:
        meta = getattr(al, "meta", None)
        if not meta or not getattr(meta, "id", None):
            continue
        mid = int(meta.id)
        if mid not in bucket:
            atividade = getattr(meta, "atividade", None)
            atividade_nome = None
            if atividade:
                atividade_nome = getattr(atividade, "titulo", None) or getattr(atividade, "nome", None)
            bucket[mid] = {
                "id": mid,
                "nome": getattr(meta, "display_titulo", None) or getattr(meta, "titulo", "(sem título)"),
                "atividade_nome": atividade_nome,
                "data_limite": getattr(meta, "data_limite", None),
                "alocado_unidade": 0,
                "executado_unidade": 0,
                "meta_total": int(getattr(meta, "quantidade_alvo", 0) or 0),
            }
        bucket[mid]["alocado_unidade"] += int(getattr(al, "quantidade_alocada", 0) or 0)
        try:
            prog_sum = al.progresso.aggregate(total=Sum("quantidade")).get("total") or 0
        except Exception:
            prog_sum = 0
        bucket[mid]["executado_unidade"] += int(prog_sum)

    metas = list(bucket.values())
    metas.sort(key=lambda x: str(x.get("nome") or "").lower())
    return JsonResponse({"metas": metas})


@require_GET
@login_required
def programacao_do_dia_orm(request):
    """
    Lê a programação do dia via ORM (sem bridge) e normaliza para o front.
    """
    iso = request.GET.get("data")
    if not iso:
        return JsonResponse({"ok": True, "itens": []})

    dia = _parse_iso(iso)
    if not dia:
        return JsonResponse({"ok": True, "itens": []})

    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        return JsonResponse({"ok": True, "itens": []})

    try:
        prog = Programacao.objects.get(unidade_id=unidade_id, data=iso)
    except Programacao.DoesNotExist:
        return JsonResponse({"ok": True, "itens": []})

    itens_qs = ProgramacaoItem.objects.filter(programacao=prog).values(
        "id", "meta_id", "observacao", "veiculo_id"
    )
    item_ids = [it["id"] for it in itens_qs]
    serv_ids_by_item: Dict[int, List[int]] = {}
    serv_objs_by_item: Dict[int, List[Dict[str, Any]]] = {}
    if item_ids:
        for link in (
            ProgramacaoItemServidor.objects.filter(item_id__in=item_ids)
            .select_related("servidor")
        ):
            iid = int(getattr(link, "item_id"))
            sid = int(getattr(link, "servidor_id"))
            serv_ids_by_item.setdefault(iid, []).append(sid)
            nome = getattr(getattr(link, "servidor", None), "nome", "") or f"Servidor {sid}"
            serv_objs_by_item.setdefault(iid, []).append({"id": sid, "nome": nome})

    itens: List[Dict[str, Any]] = []
    for it in itens_qs:
        meta_id = it["meta_id"]
        iid = int(it["id"])
        obj = {
            "id": iid,
            "meta_id": meta_id,
            "observacao": it.get("observacao") or "",
            "veiculo_id": it.get("veiculo_id"),
            "servidores_ids": serv_ids_by_item.get(iid, []),
            "servidores": serv_objs_by_item.get(iid, []),
        }
        try:
            if settings.META_EXPEDIENTE_ID and int(meta_id) == int(settings.META_EXPEDIENTE_ID):
                obj["titulo"] = "Expediente administrativo"
        except Exception:
            pass
        itens.append(obj)

    return JsonResponse({"ok": True, "itens": itens})


@login_required
@csrf_protect
@require_POST
def excluir_programacao_secure(request):
    """
    Exclui a Programacao do dia da UNIDADE atual.
    Aceita JSON: {"programacao_id": <id>} OU {"data": "YYYY-MM-DD"}.
    """
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        data = {}

    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        return JsonResponse({"ok": False, "error": "Unidade não definida."}, status=400)

    prog = None
    pid = data.get("programacao_id")
    if pid:
        try:
            prog = Programacao.objects.get(pk=pid, unidade_id=unidade_id)
        except Programacao.DoesNotExist:
            return JsonResponse({"ok": False, "error": "Programação não encontrada."}, status=404)
    else:
        iso = data.get("data")
        dia = _parse_iso(iso or "")
        if not dia:
            return JsonResponse({"ok": False, "error": "Data inválida."}, status=400)
        prog = Programacao.objects.filter(unidade_id=unidade_id, data=iso).first()
        if not prog:
            return JsonResponse({"ok": True, "deleted": False})

    prog.delete()
    return JsonResponse({"ok": True, "deleted": True})
