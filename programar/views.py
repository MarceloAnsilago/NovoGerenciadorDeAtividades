# programar/views.py
from __future__ import annotations

import html
import json
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, List
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.test.client import RequestFactory
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET
from django.contrib.auth.decorators import login_required
from core.utils import get_unidade_atual_id
from servidores.models import Servidor
from descanso.models import Descanso, Feriado
from programar.models import Programacao, ProgramacaoItem, ProgramacaoItemServidor
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseNotAllowed
from django.views.decorators.http import require_GET, require_POST
from django.utils import timezone
from metas.models import Meta, MetaAlocacao, ProgressoMeta
from veiculos.models import Veiculo
from django.db.models import Sum, Count, Q
from django.db import transaction


from django.contrib import messages
from django.views.decorators.http import require_http_methods
# =============================================================================
# Página
# =============================================================================

import unicodedata

def _norm(s:str) -> str:
    if not s: return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii","ignore").decode("ascii")
    return s.strip().lower()

def _is_expediente(nome_meta: str) -> bool:
    return _norm(nome_meta) in {"expediente administrativo", "expediente adm", "expediente"}

def _meta_status_info(meta: Any) -> tuple[str, str]:
    if not meta:
        return "andamento", "Em andamento"
    try:
        if getattr(meta, "encerrada", False):
            return "encerrada", "Encerrada"
        if getattr(meta, "concluida", False):
            return "concluida", "Concluída"
    except Exception:
        pass
    return "andamento", "Em andamento"

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
            servidor__ativo=True,
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


def _servidores_status_para_data(
    unidade_id: int | None,
    data_ref: date,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Calcula os servidores livres e impedidos para a unidade/data informadas.
    Livres: todos os servidores da unidade que nao estao marcados como impedidos.
    Impedidos: registros com id/nome/motivo consolidados (ex.: descanso).
    """
    if not unidade_id:
        return [], [], []

    impedidos_descanso, impedidos_ids = _impedidos_por_descanso(unidade_id, data_ref)

    impedidos_final: list[dict[str, Any]] = []
    for item in impedidos_descanso:
        impedidos_final.append({
            "id": item.get("id"),
            "nome": item.get("nome"),
            "motivo": item.get("motivo"),
        })

    feriados = (
        Feriado.objects.select_related("cadastro")
        .filter(cadastro__unidade_id=unidade_id, data=data_ref)
        .order_by("id")
    )
    feriados_final = [
        {
            "descricao": f.descricao or "Feriado",
            "cadastro": f.cadastro.descricao,
        }
        for f in feriados
    ]

    servidores_qs = Servidor.objects.filter(unidade_id=unidade_id, ativo=True).order_by("nome")
    if impedidos_ids:
        servidores_qs = servidores_qs.exclude(id__in=impedidos_ids)

    livres = [{"id": s.id, "nome": s.nome} for s in servidores_qs]
    return livres, impedidos_final, feriados_final


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

    livres, impedidos, feriados = _servidores_status_para_data(unidade_id, data_ref)
    return JsonResponse({"livres": livres, "impedidos": impedidos, "feriados": feriados})
def _parse_date(s: str) -> date | None:
    try:
        y, m, d = map(int, s.split("-"))
        return date(y, m, d)
    except Exception:
        return None

def _format_iso_to_br(date_str: str) -> str:
    if not date_str:
        return ""
    raw = date_str[:10]
    try:
        parsed = datetime.strptime(raw, "%Y-%m-%d").date()
        return parsed.strftime("%d/%m/%Y")
    except Exception:
        return html.escape(date_str)

def _period_label_br(start: str, end: str) -> str:
    return f"{_format_iso_to_br(start)} &#8594; {_format_iso_to_br(end)}"

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
        existentes_qs = ProgramacaoItem.objects.filter(programacao=prog).select_related("programacao")
        existentes: Dict[int, ProgramacaoItem] = {pi.id: pi for pi in existentes_qs}
        existentes_por_meta: dict[int, list[ProgramacaoItem]] = defaultdict(list)
        for pi in existentes_qs:
            try:
                meta_key = int(pi.meta_id)
            except (TypeError, ValueError):
                continue
            existentes_por_meta[meta_key].append(pi)

        ids_payload: set[int] = set()
        total_vinculos = 0

        # mapa de servidores ativos por unidade para validar entrada
        ativos_ids = set(Servidor.objects.filter(unidade_id=unidade_id, ativo=True).values_list("id", flat=True)) if unidade_id else set()

        for it in itens_in:
            raw_meta_id = it.get("meta_id")
            try:
                meta_id = int(raw_meta_id)
            except (TypeError, ValueError):
                continue

            obs = it.get("observacao") or ""
            raw_veiculo = it.get("veiculo_id")
            try:
                veiculo_id = int(raw_veiculo) if raw_veiculo not in (None, "", "null") else None
            except (TypeError, ValueError):
                veiculo_id = None

            servidores_ids: list[int] = []
            vistos_servidores: set[int] = set()
            for sid in (it.get("servidores_ids") or []):
                try:
                    sid_int = int(sid)
                except (TypeError, ValueError):
                    continue
                if ativos_ids and sid_int not in ativos_ids:
                    # ignora servidor inativo ou de outra unidade
                    continue
                if sid_int in vistos_servidores:
                    continue
                vistos_servidores.add(sid_int)
                servidores_ids.append(sid_int)

            raw_item_id = it.get("id")
            item_id: int | None = None
            pi: ProgramacaoItem | None = None

            if raw_item_id not in (None, "", "null"):
                try:
                    item_id = int(raw_item_id)
                except (TypeError, ValueError):
                    item_id = None
                if item_id and item_id in existentes:
                    pi = existentes[item_id]

            if not pi:
                candidatos = existentes_por_meta.get(meta_id, [])
                for idx, candidato in enumerate(candidatos):
                    cid = candidato.id
                    if cid in ids_payload:
                        continue
                    pi = candidato
                    item_id = cid
                    candidatos.pop(idx)
                    break

            if pi:
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

            if item_id is None:
                continue

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

        # sanitiza duplicados por meta na programação (mantém apenas um registro)
        duplicados = (
            ProgramacaoItem.objects
            .filter(programacao=prog)
            .values("meta_id")
            .annotate(total=Count("id"))
            .filter(total__gt=1)
        )
        for row in duplicados:
            meta_dup = row.get("meta_id")
            if meta_dup is None:
                continue
            itens_meta = list(
                ProgramacaoItem.objects
                .filter(programacao=prog, meta_id=meta_dup)
                .order_by("id")
            )
            if not itens_meta:
                continue

            keeper = None
            for pi in itens_meta:
                if pi.id in ids_payload:
                    keeper = pi
                    break
            if keeper is None:
                keeper = itens_meta[0]
                ids_payload.add(keeper.id)

            extras = [pi for pi in itens_meta if pi.id != keeper.id]
            if not extras:
                continue

            extra_ids = [pi.id for pi in extras]
            ProgramacaoItemServidor.objects.filter(item_id__in=extra_ids).delete()
            ProgramacaoItem.objects.filter(id__in=extra_ids).delete()

            for extra in extras:
                existentes.pop(extra.id, None)
            if meta_dup in existentes_por_meta:
                existentes_por_meta[meta_dup] = [
                    pi for pi in existentes_por_meta[meta_dup] if pi.id == keeper.id
                ]

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
            raw = getattr(resp, "content", b"")
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode(getattr(resp, "charset", "utf-8"))
            else:
                raw = str(raw or "")
            data = json.loads(raw) if str(raw).strip() else {}
            semanas = data.get("semanas") if isinstance(data, dict) else None
            if isinstance(semanas, list) and semanas:
                dedup = []
                seen = set()
                for sem in semanas:
                    for srv in (sem.get("servidores") or []):
                        # usa id quando disponivel; senao (nome,telefone)
                        key = srv.get("id")
                        if key is None:
                            key = (srv.get("nome") or "", srv.get("telefone") or "")
                        if key in seen:
                            continue
                        seen.add(key)
                        dedup.append({
                            "nome": srv.get("nome") or srv.get("servidor") or "",
                            "telefone": srv.get("telefone") or "",
                        })
                if dedup:
                    return dedup
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
        unidade_id = get_unidade_atual_id(request)
        plantao_id = request.GET.get("plantao_id") or request.session.get("plantao_id")
        qs = Semana.objects.filter(inicio__lte=de, fim__gte=ds)
        if plantao_id:
            qs = qs.filter(plantao_id=plantao_id)
        # aplica escopo por unidade quando disponivel (evita misturar outras unidades)
        if unidade_id:
            try:
                qs = qs.filter(plantao__unidade_id=unidade_id)
            except Exception:
                pass

        semanas = list(qs.order_by("ordem", "inicio"))
        if not semanas:
            return []

        out: List[Dict[str, Any]] = []
        seen: set = set()
        for sem in semanas:
            ss_qs = (
                SemanaServidor.objects.filter(semana=sem, servidor__ativo=True)
                .select_related("servidor")
                .order_by("ordem", "servidor__nome")
            )
            for ss in ss_qs:
                nome = getattr(getattr(ss, "servidor", None), "nome", "") or ""
                tel = getattr(ss, "telefone_snapshot", "") or ""
                key = (nome, tel)
                if key in seen:
                    continue
                seen.add(key)
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
# =============================================================================
# Helpers - PROGRAMACAO DA SEMANA (ORM) + render
# =============================================================================
def _fetch_programacao_dia(request, iso: str) -> list[dict[str, Any]]:
    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        return []

    try:
        prog = Programacao.objects.get(unidade_id=unidade_id, data=iso)
    except Programacao.DoesNotExist:
        return []

    itens = list(
        ProgramacaoItem.objects
        .filter(programacao=prog)
        .select_related("meta", "veiculo")
        .order_by("id")
    )
    if not itens:
        return []

    item_ids = [it.id for it in itens]
    serv_nomes: Dict[int, List[str]] = {}
    serv_ids: Dict[int, List[str]] = {}
    if item_ids:
        for link in (
            ProgramacaoItemServidor.objects
            .filter(item_id__in=item_ids, servidor__ativo=True)
            .select_related("servidor")
            .order_by("servidor__nome")
        ):
            iid = int(getattr(link, "item_id"))
            sid = int(getattr(link, "servidor_id"))
            nome = getattr(getattr(link, "servidor", None), "nome", "") or f"Servidor {sid}"
            serv_nomes.setdefault(iid, []).append(nome)
            serv_ids.setdefault(iid, []).append(str(sid))

    out: list[dict[str, Any]] = []
    for it in itens:
        meta = getattr(it, "meta", None)
        meta_id = getattr(meta, "id", None)
        meta_nome = ""
        if meta:
            meta_nome = (
                getattr(meta, "display_titulo", None)
                or getattr(meta, "titulo", None)
                or getattr(meta, "nome", None)
                or ""
            )
        if not meta_nome and meta_id is not None:
            meta_nome = f"Meta #{meta_id}"
        try:
            if settings.META_EXPEDIENTE_ID and meta_id is not None and int(meta_id) == int(settings.META_EXPEDIENTE_ID):
                meta_nome = "Expediente administrativo"
        except Exception:
            pass

        veiculo = getattr(it, "veiculo", None)
        veiculo_label = ""
        if veiculo:
            nome = getattr(veiculo, "nome", "") or ""
            placa = getattr(veiculo, "placa", "") or ""
            if nome and placa:
                veiculo_label = f"{nome} ({placa})"
            else:
                veiculo_label = nome or placa or ""

        out.append({
            "meta": meta_nome,
            "servidores": serv_nomes.get(it.id, []),
            "servidor_ids": serv_ids.get(it.id, []),
            "veiculo": veiculo_label,
        })

    return out


def _fetch_expediente_admin(
    request,
    iso: str,
    alocados_ids: set[str],
) -> tuple[list[str], list[dict[str, str]]]:
    dia = _parse_iso(iso)
    if not dia:
        return [], []

    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        return [], []

    livres, impedidos, _feriados = _servidores_status_para_data(unidade_id, dia)

    livres_map: dict[str, str] = {}
    for s in livres:
        sid_raw = s.get("id")
        if sid_raw is None:
            continue
        sid = str(sid_raw).strip()
        if not sid:
            continue
        nome = s.get("nome") or f"Servidor #{sid}"
        livres_map[sid] = nome

    impedidos_ids: set[str] = set()
    impedidos_list: list[dict[str, str]] = []
    for s in impedidos:
        sid_raw = s.get("id")
        sid = str(sid_raw).strip() if sid_raw is not None else ""
        nome = s.get("nome") or (f"Servidor #{sid}" if sid else "Servidor")
        motivo = s.get("motivo") or "Impedido"
        impedidos_list.append({"nome": nome, "motivo": motivo})
        if sid:
            impedidos_ids.add(sid)

    ok_ids = (set(livres_map.keys()) - set(alocados_ids)) - impedidos_ids
    expediente = sorted([livres_map[i] for i in ok_ids], key=str.casefold)
    return expediente, impedidos_list


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
      1) Expediente administrativo (primeiro, sem S/N)
      2) Atividades do dia (com S/N)
      3) Impedidos (informativo)

    Extras:
      - Linha divisória mais forte entre dias (tr.day-end + td.dia-cell.day-end)
      - Coluna 'Veículo' centralizada (horizontal e vertical)
      - Dedup de atividades por META (se houver uma com servidores, elimina as vazias dessa meta)
      - Cada DIA é um <tbody> separado (dia-bucket) para não quebrar no meio na impressão
      - Ao final: 'Justificativa de atividades não realizadas' por servidor
    """
    import unicodedata
    from collections import defaultdict

    # ---------- helpers ----------
    def _norm(s: str) -> str:
        if not s:
            return ""
        s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
        return s.strip().lower()

    def _norm_list(lst):
        out = []
        for x in (lst or []):
            if isinstance(x, str):
                x = x.strip()
            if x:
                out.append(x)
        return out

    def _is_expediente(nome_meta: str) -> bool:
        v = _norm(nome_meta)
        return v in {"expediente administrativo", "expediente adm", "expediente adm.", "expediente"}

    def _dedup_atividades(items):
        """
        Dedup por META (ignora veículo):
        - Se existir ao menos um item COM servidores para a meta, remove todos os itens
          vazios dessa mesma meta, mantendo todos os cheios (podem ser grupos distintos).
        - Se todos os itens da meta são vazios, mantém só o primeiro vazio.
        """
        grupos = {}  # meta_norm -> {"cheios": [it], "vazios": [it]}
        for it in items:
            meta_norm = _norm(it.get("meta", ""))
            grupos.setdefault(meta_norm, {"cheios": [], "vazios": []})
            if _norm_list(it.get("servidores")):
                grupos[meta_norm]["cheios"].append(it)
            else:
                grupos[meta_norm]["vazios"].append(it)

        out = []
        for g in grupos.values():
            if g["cheios"]:
                out.extend(g["cheios"])
            elif g["vazios"]:
                out.append(g["vazios"][0])
        return out

    ds = _parse_iso(start_iso)
    de = _parse_iso(end_iso)
    if not ds or not de:
        return "<div class='text-muted'>Intervalo inválido.</div>"

    unidade_id = get_unidade_atual_id(request)
    feriados_map = {}
    if unidade_id:
        feriados_qs = (
            Feriado.objects.select_related("cadastro")
            .filter(cadastro__unidade_id=unidade_id, data__gte=ds, data__lte=de)
            .order_by("data", "id")
        )
        for f in feriados_qs:
            feriados_map.setdefault(f.data, [])
            feriados_map[f.data].append(f.descricao or f.cadastro.descricao)

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

    tem_algum = False

    # acumula para relatório por servidor
    atividades_por_servidor = defaultdict(list)  # nome -> list[ dict(dia_label, iso, atividade, veiculo) ]

    # >>> AGORA: em vez de um tbody único, guardaremos vários <tbody> (um por dia)
    bodies_html: list[str] = []

    # ---------- loop por dia ----------
    for dt in _daterange_inclusive(ds, de):
        iso = dt.strftime("%Y-%m-%d")
        dia_label = f"{dt.strftime('%d/%m')} ({_weekday_pt_short(dt.weekday())})"

        itens = _fetch_programacao_dia(request, iso)

        # ids alocados em qualquer atividade do dia
        alocados_ids: set[str] = set()
        for it in itens:
            for sid in it.get("servidor_ids", []):
                if sid:
                    alocados_ids.add(str(sid))

        # expediente (livres - alocados) e impedidos
        expediente, impedidos = _fetch_expediente_admin(request, iso, alocados_ids)

        # Se vier "Expediente Administrativo" como atividade do legado, converte para expediente
        expediente_extra = []
        itens_atividades = []
        for it in itens:
            if _is_expediente(it.get("meta", "")):
                expediente_extra.extend(it.get("servidores") or [])
            else:
                itens_atividades.append(it)

        # Dedup por META
        itens_atividades = _dedup_atividades(itens_atividades)

        # Mescla expediente calculado + do legado (sem duplicar nomes)
        if expediente_extra:
            seen = set()
            exp_merge = []
            for nome in list(expediente) + expediente_extra:
                if nome not in seen:
                    seen.add(nome)
                    exp_merge.append(nome)
            expediente = exp_merge

        feriados_do_dia = feriados_map.get(dt) or []

        # Monta os blocks garantindo feriados/expediente primeiro
        blocks: list[dict] = []
        if feriados_do_dia:
            blocks.append({"kind": "feriado", "descricoes": feriados_do_dia})
        if expediente:
            blocks.append({"kind": "expediente", "servidores": expediente})
        for it in itens_atividades:
            blocks.append({
                "kind": "atividade",
                "meta": it["meta"],
                "servidores": it["servidores"],
                "veiculo": it["veiculo"],
            })
        if impedidos:
            blocks.append({"kind": "impedidos", "dados": impedidos})

        if dt.weekday() >= 5:
            has_atividade = any(b["kind"] in {"atividade", "feriado"} for b in blocks)
            if not has_atividade:
                # ignora sábados/domingos sem atividades programadas
                continue

        total = len(blocks)

        # linhas desse DIA
        day_rows: list[str] = []

        if total == 0:
            day_rows.append(
                "<tr class='day-end'>"
                f"<td class='dia-cell day-end'>{html.escape(dia_label)}</td>"
                "<td colspan='4' class='text-muted'>Sem programação.</td>"
                "</tr>"
            )
            # empacota o dia mesmo assim
            bodies_html.append("<tbody class='dia-bucket'>" + "".join(day_rows) + "</tbody>")
            continue

        tem_algum = True

        for idx, b in enumerate(blocks):
            is_last = (idx == total - 1)
            tr_class = "day-end" if is_last else ""
            open_tr = f"<tr class='{tr_class}'>"
            dia_td = ""
            if idx == 0:
                # TD do dia também com classe day-end para borda atravessar rowSpan
                dia_td = f"<td class='dia-cell day-end' rowspan='{total}'>{html.escape(dia_label)}</td>"

            if b["kind"] == "feriado":
                desc_lines = "".join(
                    f"<div class='feriado-desc'>{html.escape(desc)}</div>"
                    for desc in b.get("descricoes", [])
                )
                if not desc_lines:
                    desc_lines = "<span class='text-muted'>-</span>"
                day_rows.append(
                    open_tr
                    + dia_td
                    + "<td class='atividade-cell'><em>Feriado</em></td>"
                    + f"<td>{desc_lines}</td>"
                    + "<td class='veiculo-cell text-nowrap'>-</td>"
                    + "<td class='realizada-cell'>-</td>"
                    + "</tr>"
                )

            elif b["kind"] == "expediente":
                day_rows.append(
                    open_tr
                    + dia_td
                    + "<td class='atividade-cell'><em>Expediente administrativo</em></td>"
                    + f"<td>{_srv_list_html(b['servidores'], with_boxes=False, inline=True)}</td>"
                    + "<td class='veiculo-cell text-nowrap'>—</td>"
                    + "<td class='realizada-cell'>—</td>"
                    + "</tr>"
                )

            elif b["kind"] == "atividade":
                # acumula para rel. atividades
                for nome in (b.get("servidores") or []):
                    if nome and isinstance(nome, str):
                        atividades_por_servidor[nome].append({
                            "dia_label": dia_label,
                            "iso": iso,
                            "atividade": b["meta"],
                            "veiculo": b["veiculo"],
                        })

                day_rows.append(
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
                day_rows.append(
                    open_tr
                    + dia_td
                    + "<td class='atividade-cell'><em>Impedidos</em></td>"
                    + f"<td>{imp_lines}</td>"
                    + "<td class='veiculo-cell text-nowrap'>—</td>"
                    + "<td class='realizada-cell'>—</td>"
                    + "</tr>"
                )

        # empacota o DIA num <tbody> próprio (anti quebra)
        bodies_html.append("<tbody class='dia-bucket'>" + "".join(day_rows) + "</tbody>")

    # ---------- CSS embutido ----------
    style = (
        "<style>"
        "/* ====== RELATÓRIO ====== */"
        ".report-container{ max-width:1200px; margin-left:auto; margin-right:auto; padding:0 0.5rem; }"
        ".report-toolbar{ display:flex; align-items:center; gap:.35rem; }"
        ".report-toolbar .btn{ min-width:110px; }"
        ".report-toolbar .btn i{ margin-right:.35rem; }"
        "/* ====== TELA ====== */"
        ".programacao-semana-table .feriado-desc{ color:#842029; font-weight:600; }"
        ".programacao-semana-table tbody td.veiculo-cell{"
        "  text-align:center !important; vertical-align:middle !important;"
        "}"
        ".programacao-semana-table tbody tr.day-end > td,"
        ".programacao-semana-table tbody td.dia-cell.day-end{"
        "  border-bottom: 1px solid #000 !important;"
        "}"
        ".programacao-semana-table th:first-child, .programacao-semana-table td.dia-cell{ min-width:110px; }"
        ".programacao-semana-table td, .programacao-semana-table th{ vertical-align: top; }"

        "/* Relatório 'Justificativa' */"
        ".rel-atividades .card-ativ{ page-break-inside: avoid; }"
        ".rel-atividades .mini-table{ width:100%; border-collapse:collapse; }"
        ".rel-atividades .mini-table td{ border:1px solid var(--bs-border-color); padding:.35rem .5rem; }"
        ".rel-atividades .mini-table .lbl{ width:180px; white-space:nowrap; }"
        ".rel-atividades .mini-table .just{ height:2.2rem; }"
        ".rel-atividades .servidor-title{ font-weight:600; margin-bottom:.35rem; }"

        "/* ====== IMPRESSÃO ====== */"
        "@media print{"
        "  .programacao-semana-table .dia-bucket{"
        "    break-inside: avoid; page-break-inside: avoid;"
        "  }"
        "  .programacao-semana-table tr, .programacao-semana-table td{"
        "    break-inside: avoid; page-break-inside: avoid;"
        "  }"

        "  .programacao-semana-table{"
        "    border-collapse: collapse !important;"
        "    table-layout: fixed;"
        "    font-size: 11px;"
        "  }"
        "  .programacao-semana-table th, .programacao-semana-table td{"
        "    padding: 2pt 4pt !important;"
        "    line-height: 1.15 !important;"
        "    border-top: 0.5pt solid #000 !important;"
        "    vertical-align: top;"
        "  }"
        "  .programacao-semana-table th:first-child, .programacao-semana-table td.dia-cell{"
        "    min-width: 90px !important; width: 90px !important;"
        "  }"
        "  .print-cbx{ width:10px; height:10px; margin:0 3px 0 4px; border-width:1.2px; }"
        "  .programacao-semana-table thead th{"
        "    border-bottom: 0.75pt solid #000 !important;"
        "    border-top: 0.5pt solid #000 !important;"
        "  }"
        "  .programacao-semana-table tbody tr.day-end > td,"
        "  .programacao-semana-table tbody td.dia-cell.day-end{"
        "    border-bottom: 0.5pt solid #000 !important;"
        "  }"
        "  .rel-atividades .mini-table td{ padding:.25rem .35rem !important; }"
        "  .programacao-semana-table td.veiculo-cell{"
        "    text-align: center !important;"
        "    vertical-align: middle !important;"
        "  }"
        "  div.mt-4.rel-atividades{ break-before: page; page-break-before: always; }"
        "  .report-toolbar, .report-toolbar .btn, .report-toolbar .btn-group, .btn{ display:none !important; }"
        "}"
        "</style>"
    )

    # ---------- bloco principal (programação da semana) ----------
    bloco_programacao = (
        "<div id='programar-programacao-semana-block' class='mt-3'>"
        "<h6 class='fw-semibold mb-2'><i class='bi bi-table me-1'></i> Programação da semana</h6>"
        "<div class='table-responsive'>"
        "<table class='table table-sm align-middle mb-0 programacao-semana-table'>"
        "<thead class='table-light'>"
        "<tr>"
        "<th style='width:90px'>Dia</th>"
        "<th>Atividade</th>"
        "<th>Servidores</th>"
        "<th style='width:200px'>Veículo</th>"
        "<th style='width:140px'>Realizada</th>"
        "</tr>"
        "</thead>"
        + "".join(bodies_html) +  # <<< vários <tbody>, um por dia
        "</table></div>"
        + (""
           if any(bodies_html) else
           "<div class='text-muted mt-2'>Nenhuma atividade nesta semana.</div>")
        + "</div>"
    )

    # ---------- RELATÓRIO DE ATIVIDADES (embaixo) ----------
    servidores_ordenados = sorted(atividades_por_servidor.keys(), key=str.casefold)

    cards: list[str] = []
    for nome in servidores_ordenados:
        itens = atividades_por_servidor[nome]
        if not itens:
            continue

        linhas = []
        itens_sorted = sorted(itens, key=lambda x: (x["iso"], x["atividade"]))
        for it in itens_sorted:
            dia = html.escape(it["dia_label"])
            atividade = html.escape(it.get("atividade") or "")

            # 1ª linha: dia + atividade
            linhas.append(
                "<tr>"
                "<td class='lbl'>Dia</td>"
                f"<td>{dia}" + (f": {atividade}" if atividade else "") + "</td>"
                "</tr>"
            )
            # 2ª linha: apenas “Justificativa” com linha
            linhas.append(
                "<tr>"
                "<td class='lbl'>Justificativa</td>"
                "<td>"
                "<span class='just d-inline-block' "
                "style='display:inline-block;border-bottom:1px solid var(--bs-border-color);width:100%;'></span>"
                "</td>"
                "</tr>"
            )

        cards.append(
            "<div class='card card-ativ border-0 shadow-sm mb-3 rel-atividades'>"
            "<div class='card-body p-3'>"
            f"<div class='servidor-title'><i class='bi bi-person me-1'></i>Servidor: {html.escape(nome)}</div>"
            "<table class='mini-table'><tbody>"
            + "".join(linhas) +
            "</tbody></table>"
            "</div></div>"
        )

    bloco_atividades = (
        "<div class='mt-4 rel-atividades'>"
        "<h6 class='fw-semibold mb-2'><i class='bi bi-list-check me-1'></i> Justificativa de atividades não realizadas</h6>"
        + ("".join(cards) if cards else "<div class='text-muted'>Nenhuma atividade para os servidores no período.</div>")
        + "</div>"
    )

    # flags para filtrar conteúdo: permitem forçar via atributo do request
    try:
        only_just = bool(getattr(request, "_force_only_just", False)) or (
            str(request.GET.get("only_just", "")).strip().lower() in {"1", "true", "yes", "on", "y"}
        )
    except Exception:
        only_just = bool(getattr(request, "_force_only_just", False))
    if only_just:
        return style + bloco_atividades
    try:
        hide_just = bool(getattr(request, "_force_hide_just", False)) or (
            str(request.GET.get("hide_just", "")).strip().lower() in {"1", "true", "yes", "on", "y"}
        )
    except Exception:
        hide_just = bool(getattr(request, "_force_hide_just", False))
    if hide_just:
        return style + bloco_programacao
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
    period_label = _period_label_br(start, end)

    html_out = f"""
    <div id="relatorioPrintArea" class="card border-0 shadow-sm">
      <div class="card-body">
        <div class="container mt-3 report-container px-0">
          <div class="d-flex justify-content-between align-items-center mb-3">
            <h2 class="mb-0">
              <i class="bi bi-list-check me-2"></i> Relatório de atividades
            </h2>
            <div id="relatorio-toolbar" class="report-toolbar no-print">
              <div class="btn-group btn-group-sm">
                <button id="relatorio-btn-print" type="button" class="btn btn-outline-secondary" title="Imprimir relatório">
                  <i class="bi bi-printer me-1"></i> Imprimir
                </button>
              </div>
            </div>
          </div>
          <div class="text-muted small mb-3">
            Período: <strong>{period_label}</strong>
          </div>
          <div class="card shadow-sm border-0">
            <div class="card-body p-0">
              <div class="mb-3">{plantonistas_html}</div>
              <hr class="my-3">
              {tabela_semana_html}
            </div>
          </div>
        </div>
      </div>
    </div>
    """
    # Override do wrapper quando pedirem apenas justificativas (sem cabeçalho)
    try:
        __only = str(request.GET.get("only_just", "")).strip().lower() in {"1","true","yes","on","y"}
    except Exception:
        __only = False
    try:
        __hide = str(request.GET.get("hide_just", "")).strip().lower() in {"1","true","yes","on","y"}
    except Exception:
        __hide = False
    if __only and not __hide:
        html_out = f"""
        <div id=\"relatorioPrintArea\" class=\"card border-0 shadow-sm\">
          <div class=\"card-body\">
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

    # força ocultar justificativas neste modo de impressão
    try:
        q = request.GET.copy()
        q["hide_just"] = "1"
        request.GET = q
    except Exception:
        pass
    # fallback robusto via atributo no request
    try:
        setattr(request, "_force_hide_just", True)
    except Exception:
        pass

    servidores = _fetch_plantonistas_via_bridge(request, start, end)
    if not servidores:
        servidores = _fetch_plantonistas_via_orm(request, start, end)

    plantonistas_html = _render_plantonistas_html(servidores, start, end)
    tabela_semana_html = _render_programacao_semana_html(request, start, end)
    period_label = _period_label_br(start, end)

    html_out = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Relatório {period_label}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css" rel="stylesheet">
  <style>
    body{{padding:8px; font-size:11px}}
    @page{{ margin:8mm; }}
    .report-container{{ max-width:1100px; margin:0 auto; }}
    .report-toolbar{{ display:flex; align-items:center; gap:.35rem; }}
    .report-toolbar .btn{{ min-width:110px; }}
    @media print{{ .report-toolbar, .report-toolbar .btn, .no-print {{display:none!important;}} }}
  </style>
</head>
<body>
  <div class="container mt-3 report-container">
    <div class="d-flex justify-content-between align-items-center mb-3 no-print">
      <h3 class="mb-0">Relatório semanal</h3>
      <div class="report-toolbar">
        <button type="button" class="btn btn-outline-secondary btn-sm" onclick="window.print()">
          <i class="bi bi-printer me-1"></i> Imprimir
        </button>
      </div>
    </div>
    <div class="text-muted small mb-3">Período: <strong>{period_label}</strong></div>
    <div class="card border-0 shadow-sm">
      <div class="card-body p-0">
        <div class="mb-3">{plantonistas_html}</div>
        <div>{tabela_semana_html}</div>
      </div>
    </div>
  </div>
</body>
</html>"""
    return HttpResponse(html_out)


@login_required
@require_GET
def print_relatorio_justificativas(request):
    start = request.GET.get("start", "")
    end = request.GET.get("end", "")

    # força modo somente justificativas via query flag
    try:
        q = request.GET.copy()
        q["only_just"] = "1"
        request.GET = q
    except Exception:
        pass
    # fallback robusto via atributo no request
    try:
        setattr(request, "_force_only_just", True)
    except Exception:
        pass

    tabela_semana_html = _render_programacao_semana_html(request, start, end)
    period_label = _period_label_br(start, end)

    html_out = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Justificativas {period_label}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css" rel="stylesheet">
  <style>
    body{{padding:8px; font-size:11px}}
    @page{{ margin:8mm; }}
    .report-container{{ max-width:1100px; margin:0 auto; }}
    .report-toolbar{{ display:flex; align-items:center; gap:.35rem; }}
    .report-toolbar .btn{{ min-width:110px; }}
    @media print{{ .report-toolbar, .report-toolbar .btn, .no-print {{display:none!important;}} }}
  </style>
</head>
<body>
  <div class="container mt-3 report-container">
    <div class="d-flex justify-content-between align-items-center mb-3 no-print">
      <h3 class="mb-0">Justificativa de atividades não realizadas</h3>
      <div class="report-toolbar">
        <button type="button" class="btn btn-outline-secondary btn-sm" onclick="window.print()">
          <i class="bi bi-printer me-1"></i> Imprimir
        </button>
      </div>
    </div>
    <div class="text-muted small mb-3">Período: <strong>{period_label}</strong></div>
    <div class="card border-0 shadow-sm">
      <div class="card-body p-0">
        {tabela_semana_html}
      </div>
    </div>
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

    qs = Programacao.objects.filter(unidade_id=unidade_id).order_by("data")
    if start_date:
        qs = qs.filter(data__gte=start_date)
    if end_date:
        qs = qs.filter(data__lte=end_date)

    programacoes = list(qs.values("id", "data", "concluida"))
    prog_ids = [p["id"] for p in programacoes]
    counts: Dict[int, Dict[str, int]] = {pid: {"total": 0, "concluidas": 0} for pid in prog_ids}
    metas_por_programacao: Dict[int, list[str]] = {pid: [] for pid in prog_ids}
    atividades_por_programacao: Dict[int, list[Dict[str, Any]]] = {pid: [] for pid in prog_ids}

    if prog_ids:
        itens_qs = ProgramacaoItem.objects.filter(programacao_id__in=prog_ids)
        meta_expediente_id = getattr(settings, "META_EXPEDIENTE_ID", None)
        if meta_expediente_id is not None:
            itens_qs = itens_qs.exclude(meta_id=meta_expediente_id)
        itens_qs = itens_qs.exclude(meta_id__isnull=True)

        itens_stats = (
            itens_qs
            .values("programacao_id")
            .annotate(
                total=Count("id"),
                concluidas=Count("id", filter=Q(concluido=True)),
            )
        )
        for row in itens_stats:
            pid = row.get("programacao_id")
            if pid in counts:
                counts[pid] = {
                    "total": int(row.get("total") or 0),
                    "concluidas": int(row.get("concluidas") or 0),
                }
        seen_por_prog: Dict[int, set[str]] = {pid: set() for pid in prog_ids}
        seen_ativ_por_prog: Dict[int, set[tuple[str, bool]]] = {pid: set() for pid in prog_ids}
        itens_com_meta = itens_qs.select_related("meta", "meta__atividade").order_by("programacao_id", "meta__titulo")
        for item in itens_com_meta:
            pid = item.programacao_id
            if pid not in metas_por_programacao:
                continue
            meta = getattr(item, "meta", None)
            if not meta:
                continue
            titulo = getattr(meta, "display_titulo", None)
            if not titulo:
                titulo = getattr(meta, "titulo", None)
            if not titulo:
                atividade = getattr(meta, "atividade", None)
                if atividade:
                    titulo = getattr(atividade, "titulo", None) or getattr(atividade, "nome", None)
            if not titulo:
                continue
            titulo = str(titulo).strip()
            if not titulo:
                continue
            if titulo not in seen_por_prog[pid]:
                seen_por_prog[pid].add(titulo)
                metas_por_programacao[pid].append(titulo)

            concluido_item = bool(getattr(item, "concluido", False))
            key = (titulo, concluido_item)
            if key in seen_ativ_por_prog[pid]:
                continue
            seen_ativ_por_prog[pid].add(key)
            atividades_por_programacao[pid].append({
                "titulo": titulo,
                "concluido": concluido_item,
            })

    data = []
    for prog in programacoes:
        pid = prog["id"]
        contadores = counts.get(pid, {"total": 0, "concluidas": 0})
        total = contadores["total"]
        if total == 0:
            continue
        concluidas = contadores["concluidas"]

        nome_atividades = metas_por_programacao.get(pid) or []
        nome_titulo = "; ".join(nome_atividades) if nome_atividades else ""
        total_label = f"{total} atividade{'s' if total != 1 else ''}"
        concluidas_label = f"{concluidas} concluida{'s' if concluidas != 1 else ''}"
        title = nome_titulo or f"({total_label} | {concluidas_label})"
        if prog.get("concluida"):
            title = "[Concluída] " + title

        data.append({
            "id": pid,
            "title": title,
            "start": prog["data"].isoformat(),
            "allDay": True,
            "isHoliday": 0,
            "extendedProps": {
                "total_programadas": total,
                "total_concluidas": concluidas,
                "nomes_atividades": nome_atividades,
                "atividades": atividades_por_programacao.get(pid, []),
            },
        })
    return JsonResponse(data, safe=False)


@login_required
@require_GET
def metas_disponiveis(request):
    """Metas alocadas para a UNIDADE atual (com somas alocado/executado)."""
    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        return JsonResponse({"metas": []})

    atividade_id = request.GET.get("atividade")
    qs = (
        MetaAlocacao.objects
        .select_related("meta", "meta__atividade")
        .filter(unidade_id=unidade_id, meta__encerrada=False)
        .order_by("meta__data_limite", "meta__titulo")
    )
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
            status_key, status_label = _meta_status_info(meta)
            bucket[mid] = {
                "id": mid,
                "nome": getattr(meta, "display_titulo", None) or getattr(meta, "titulo", "(sem título)"),
                "atividade_nome": atividade_nome,
                "data_limite": getattr(meta, "data_limite", None),
                "alocado_unidade": 0,
                "executado_unidade": 0,
                "meta_total": int(getattr(meta, "quantidade_alvo", 0) or 0),
                "status": status_key,
                "status_label": status_label,
            }
        bucket[mid]["alocado_unidade"] += int(getattr(al, "quantidade_alocada", 0) or 0)
        try:
            prog_sum = al.progresso.aggregate(total=Sum("quantidade")).get("total") or 0
        except Exception:
            prog_sum = 0
        bucket[mid]["executado_unidade"] += int(prog_sum)
        bucket[mid].setdefault("programadas_total", 0)

    meta_ids = list(bucket.keys())
    if meta_ids:
        itens_stats = (
            ProgramacaoItem.objects
            .filter(meta_id__in=meta_ids)
            .values("meta_id")
            .annotate(total=Count("id"))
        )
        for row in itens_stats:
            mid = int(row.get("meta_id") or 0)
            if mid in bucket:
                bucket[mid]["programadas_total"] = int(row.get("total") or 0)

    metas = list(bucket.values())
    metas.sort(
        key=lambda x: (
            x.get("data_limite") is None,
            x.get("data_limite") or date.max,
            str(x.get("nome") or "").lower(),
        )
    )
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
        "id", "meta_id", "observacao", "veiculo_id", "concluido"
    )
    item_ids = [it["id"] for it in itens_qs]
    serv_ids_by_item: Dict[int, List[int]] = {}
    serv_objs_by_item: Dict[int, List[Dict[str, Any]]] = {}
    if item_ids:
        for link in (
            ProgramacaoItemServidor.objects.filter(item_id__in=item_ids, servidor__ativo=True)
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
            "concluido": bool(it.get("concluido")),
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

@login_required
@csrf_protect
@require_POST
def marcar_item_realizada(request, item_id: int):
    """
    Marca/Desmarca ProgramacaoItem.concluido, garantindo que o item pertence
    à UNIDADE atual do usuário.
    Body JSON: {"realizada": true|false}
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = {}
    realizada = bool(payload.get("realizada", True))

    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        return JsonResponse({"ok": False, "error": "Unidade não definida."}, status=400)

    try:
        pi = (
            ProgramacaoItem.objects
            .select_related("programacao")
            .get(pk=item_id, programacao__unidade_id=unidade_id)
        )
    except ProgramacaoItem.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Item não encontrado."}, status=404)

    pi.concluido = realizada
    pi.save(update_fields=["concluido"])

    return JsonResponse({"ok": True, "item_id": pi.id, "realizada": pi.concluido})


@login_required
@require_http_methods(["GET", "POST"])
@csrf_protect
def concluir_item_form(request, item_id: int):
    """Permite marcar um item da programacao como realizado ou nao com observacao."""
    pi = (
        ProgramacaoItem.objects
        .select_related("programacao", "meta", "veiculo")
        .get(pk=item_id)
    )
    prog = pi.programacao
    unidade_id = getattr(prog, "unidade_id", None)
    meta = pi.meta
    source_context = (request.GET.get("source") or request.POST.get("source") or "").strip().lower()
    ignorar_pendentes = source_context == "minhas-metas"

    links = (
        ProgramacaoItemServidor.objects
        .select_related("servidor")
        .filter(item_id=pi.id, servidor__ativo=True)
        .order_by("servidor__nome")
    )
    servidores = [getattr(l.servidor, "nome", f"Servidor {l.servidor_id}") for l in links]

    meta = getattr(pi, "meta", None)
    programacao = pi.programacao

    pendentes_qs = ProgramacaoItem.objects.none()
    pendentes_total = 0
    pendentes_preview: list[dict[str, Any]] = []
    pendentes_tem_mais = False
    if (not ignorar_pendentes) and meta and getattr(meta, "id", None):
        pendentes_qs = (
            ProgramacaoItem.objects
            .select_related("programacao", "veiculo")
            .filter(meta_id=meta.id, concluido=False)
            .exclude(pk=pi.id)
            .order_by("programacao__data", "id")
        )
        pendentes_total = pendentes_qs.count()
        preview_limit = 5
        for pend in pendentes_qs[:preview_limit]:
            pend_prog = getattr(pend, "programacao", None)
            pend_data = getattr(pend_prog, "data", None)
            pendentes_preview.append({
                "id": pend.id,
                "data": pend_data,
                "veiculo": getattr(getattr(pend, "veiculo", None), "nome", "") or "",
            })
        pendentes_tem_mais = pendentes_total > len(pendentes_preview)

    if request.method == "POST":
        realizado_raw = (request.POST.get("realizado") or "").strip().lower()
        concluido_flag = realizado_raw in {"1", "true", "on", "sim"}
        obs_final = (request.POST.get("observacoes") or "").strip()
        confirmar_pendentes = (request.POST.get("confirmar_pendentes") or "").strip() == "1"

        if (not ignorar_pendentes) and concluido_flag and pendentes_total > 0 and not confirmar_pendentes:
            # exige confirmacao explícita antes de concluir com pendencias
            pi.concluido = concluido_flag
            contexto = {
                "item": pi,
                "programacao": programacao,
                "meta": meta,
                "atividade": getattr(meta, "atividade", None),
                "veiculo": getattr(pi, "veiculo", None),
                "servidores": servidores,
                "next": request.POST.get("next") or "/minhas-metas/",
                "pendentes_total": pendentes_total,
                "pendentes_preview": pendentes_preview,
                "pendentes_tem_mais": pendentes_tem_mais,
                "pendentes_confirmacao_obrigatoria": True,
                "confirmar_pendentes_checked": confirmar_pendentes,
                "source": source_context,
            }
            return render(request, "minhas_metas/concluir_item.html", contexto)

        if concluido_flag and not pi.concluido and unidade_id and meta and getattr(meta, "id", None):
            aloc = (
                MetaAlocacao.objects
                .filter(meta_id=meta.id, unidade_id=unidade_id)
                .order_by("id")
                .first()
            )
            if aloc:
                ProgressoMeta.objects.create(
                    data=getattr(prog, "data", timezone.localdate()),
                    quantidade=1,
                    observacao=obs_final or "",
                    alocacao_id=aloc.id,
                    registrado_por_id=getattr(request.user, "id", None),
                )
            else:
                messages.warning(
                    request,
                    "Nao encontrei alocacao desta meta para a unidade. O progresso nao foi registrado.",
                )

        if concluido_flag:
            concluido_em = timezone.now()
            concluido_por_id = getattr(request.user, "id", None)
        else:
            concluido_em = None
            concluido_por_id = None

        ProgramacaoItem.objects.filter(pk=pi.pk).update(
            concluido=concluido_flag,
            concluido_em=concluido_em,
            concluido_por_id=concluido_por_id,
            observacao=obs_final,
        )

        messages.success(request, "Item atualizado com sucesso.")
        back_url = request.GET.get("next") or request.POST.get("next") or "/minhas-metas/"
        return redirect(back_url)

    contexto = {
        "item": pi,
        "programacao": programacao,
        "meta": meta,
        "atividade": getattr(meta, "atividade", None),
        "veiculo": getattr(pi, "veiculo", None),
        "servidores": servidores,
        "next": request.GET.get("next") or request.META.get("HTTP_REFERER", "/minhas-metas/"),
        "pendentes_total": pendentes_total,
        "pendentes_preview": pendentes_preview,
        "pendentes_tem_mais": pendentes_tem_mais,
        "pendentes_confirmacao_obrigatoria": False,
        "confirmar_pendentes_checked": False,
        "source": source_context,
    }
    return render(request, "minhas_metas/concluir_item.html", contexto)
