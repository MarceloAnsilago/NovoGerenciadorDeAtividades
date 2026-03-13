# programar/views.py
from __future__ import annotations

import html
import json
import logging
from collections import defaultdict
from calendar import monthrange
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
from core.utils.security import safe_next_url
from servidores.models import Servidor
from descanso.models import Descanso, Feriado
from programar.models import Programacao, ProgramacaoItem, ProgramacaoItemServidor
from programar.status import (
    EXECUTADA,
    NAO_REALIZADA,
    NAO_REALIZADA_JUSTIFICADA,
    PENDENTE,
    REMARCADA_CONCLUIDA,
    is_auto_concluida_expediente,
    item_execucao_status_from_fields,
)
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseNotAllowed
from django.views.decorators.http import require_GET, require_POST
from django.utils import timezone
from metas.models import Meta, MetaAlocacao, ProgressoMeta
from veiculos.models import Veiculo
from django.db.models import Sum, Count, Q
from django.db import transaction
from relatorios.services.programacao_history_service import (
    record_programacao_day_diff_after_commit,
    snapshot_programacao_dia,
)


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
        if getattr(meta, "atrasada", False):
            return "atrasada", "Atrasada"
    except Exception:
        pass
    return "andamento", "Em andamento"


def _meta_ids_com_itens_abertos(
    unidade_id: int | None,
    *,
    reference_month_start: date | None = None,
) -> set[int]:
    if not unidade_id:
        return set()
    itens_qs = (
        ProgramacaoItem.objects
        .filter(
            programacao__unidade_id=unidade_id,
            concluido=False,
            nao_realizada_justificada=False,
            meta_id__isnull=False,
        )
    )
    if reference_month_start:
        itens_qs = itens_qs.filter(
            programacao__data__lt=reference_month_start,
            meta__data_limite__isnull=False,
            meta__data_limite__lt=reference_month_start,
        )
    ids = (
        itens_qs
        .values_list("meta_id", flat=True)
        .distinct()
    )
    return {int(meta_id) for meta_id in ids if meta_id}


def _resolve_remarcado_de_id(
    *,
    unidade_id: int | None,
    meta_id: int | None,
    raw_value,
    ignore_item_id: int | None = None,
) -> int | None:
    if not unidade_id or not meta_id or raw_value in (None, "", "null"):
        return None
    try:
        candidate_id = int(raw_value)
    except (TypeError, ValueError):
        return None
    qs = ProgramacaoItem.objects.filter(
        id=candidate_id,
        programacao__unidade_id=unidade_id,
        meta_id=meta_id,
        concluido=False,
        concluido_em__isnull=False,
        nao_realizada_justificada=False,
    )
    if ignore_item_id:
        qs = qs.exclude(id=ignore_item_id)
    return candidate_id if qs.exists() else None


def _build_remarcacao_opcoes(
    *,
    unidade_id: int | None,
    item: ProgramacaoItem,
) -> list[dict[str, Any]]:
    meta_id = getattr(item, "meta_id", None)
    programacao = getattr(item, "programacao", None)
    data_atual = getattr(programacao, "data", None)
    if not unidade_id or not meta_id or not data_atual:
        return []

    candidatos_qs = (
        ProgramacaoItem.objects
        .select_related("programacao", "veiculo")
        .filter(
            meta_id=meta_id,
            programacao__unidade_id=unidade_id,
            concluido=False,
            concluido_em__isnull=False,
            nao_realizada_justificada=False,
            programacao__data__lt=data_atual,
        )
        .exclude(pk=item.pk)
        .order_by("-programacao__data", "-id")
    )
    candidatos = list(candidatos_qs)
    if not candidatos:
        return []

    candidate_ids = [cand.id for cand in candidatos]
    usados_ids = set(
        ProgramacaoItem.objects
        .filter(remarcado_de_id__in=candidate_ids)
        .exclude(pk=item.pk)
        .values_list("remarcado_de_id", flat=True)
    )
    current_source_id = getattr(item, "remarcado_de_id", None)

    opcoes: list[dict[str, Any]] = []
    for cand in candidatos:
        if cand.id in usados_ids and cand.id != current_source_id:
            continue
        cand_prog = getattr(cand, "programacao", None)
        cand_data = getattr(cand_prog, "data", None)
        veiculo = getattr(getattr(cand, "veiculo", None), "nome", "") or ""
        label = f"{cand_data:%d/%m/%Y} - Item #{cand.id}"
        if veiculo:
            label += f" - {veiculo}"
        opcoes.append({
            "id": cand.id,
            "label": label,
            "data": cand_data,
            "observacao": getattr(cand, "observacao", "") or "",
        })
    return opcoes


@login_required
@require_GET
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
        periodo = f"{d.data_inicio:%d/%m}-{d.data_fim:%d/%m}"
        motivo = f"{tipo_label} ({periodo})"
        obs = getattr(d, "observacoes", None)
        if obs:
            motivo += f" - {obs}"
        impedidos_map[d.servidor_id] = {
            "id": d.servidor_id,
            "nome": d.servidor.nome,
            "motivo": motivo,
            "origem": "descanso",
        }
    return list(impedidos_map.values()), set(impedidos_map.keys())


def _plantonistas_por_data(unidade_id: int | None, data_ref: date) -> list[dict[str, Any]]:
    if not unidade_id:
        return []

    try:
        from plantao.models import SemanaServidor  # type: ignore
    except Exception:
        return []

    qs = (
        SemanaServidor.objects
        .select_related("servidor", "semana", "semana__plantao")
        .filter(
            servidor__ativo=True,
            semana__inicio__lte=data_ref,
            semana__fim__gte=data_ref,
            # Garante que o dia também esteja dentro do período oficial do plantão.
            # Evita "vazamento" dos dias extras da semana (ex.: sab->sex) entre meses.
            semana__plantao__inicio__lte=data_ref,
            semana__plantao__fim__gte=data_ref,
        )
    )

    # prioridade para o recorte da unidade do plantao; fallback para unidade do servidor
    try:
        qs = qs.filter(semana__plantao__unidade_id=unidade_id)
    except Exception:
        qs = qs.filter(servidor__unidade_id=unidade_id)

    qs = qs.order_by("ordem", "servidor__nome", "id")

    plantao_map: Dict[int, dict[str, Any]] = {}
    for item in qs:
        sid = int(getattr(item, "servidor_id", 0) or 0)
        if not sid or sid in plantao_map:
            continue

        servidor_nome = getattr(getattr(item, "servidor", None), "nome", "") or ""
        semana = getattr(item, "semana", None)
        inicio = getattr(semana, "inicio", None)
        fim = getattr(semana, "fim", None)
        periodo = ""
        if inicio and fim:
            periodo = f"{inicio:%d/%m} a {fim:%d/%m}"

        plantao_map[sid] = {
            "id": sid,
            "nome": servidor_nome,
            "periodo": periodo,
        }

    return list(plantao_map.values())


def _servidores_status_para_data(
    unidade_id: int | None,
    data_ref: date,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Calcula os servidores livres e impedidos para a unidade/data informadas.
    Livres: todos os servidores da unidade que nao estao marcados como impedidos.
    Impedidos: registros com id/nome/motivo consolidados (ex.: descanso).
    """
    if not unidade_id:
        return [], [], [], []

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
    plantao_final = _plantonistas_por_data(unidade_id, data_ref)
    plantao_final.sort(key=lambda x: str(x.get("nome") or "").lower())

    servidores_qs = Servidor.objects.filter(unidade_id=unidade_id, ativo=True).order_by("nome")
    if impedidos_ids:
        servidores_qs = servidores_qs.exclude(id__in=impedidos_ids)

    livres = [{"id": s.id, "nome": s.nome} for s in servidores_qs]
    return livres, impedidos_final, feriados_final, plantao_final


@login_required
@require_GET
def servidores_para_data(request):
    data_str = request.GET.get("data")
    if not data_str:
        return JsonResponse({"livres": [], "impedidos": [], "feriados": [], "plantao": []})
    try:
        data_ref = datetime.strptime(data_str, "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse({"livres": [], "impedidos": [], "feriados": [], "plantao": []})

    unidade_id = get_unidade_atual_id(request)

    livres, impedidos, feriados, plantao = _servidores_status_para_data(unidade_id, data_ref)
    return JsonResponse({"livres": livres, "impedidos": impedidos, "feriados": feriados, "plantao": plantao})


@login_required
@require_GET
def servidores_impedidos_mes(request):
    mes = (request.GET.get("mes") or "").strip()
    periodo = _month_range_from_ym(mes)
    if not periodo:
        return JsonResponse({"mes": mes, "impedidos": []})

    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        return JsonResponse({"mes": mes, "impedidos": []})

    inicio, fim = periodo
    qs = (
        Descanso.objects
        .select_related("servidor")
        .filter(
            servidor__unidade_id=unidade_id,
            servidor__ativo=True,
            data_inicio__lte=fim,
            data_fim__gte=inicio,
        )
        .order_by("servidor__nome", "-data_inicio", "-id")
    )

    impedidos_map: Dict[int, dict] = {}
    for d in qs:
        sid = d.servidor_id
        item = impedidos_map.get(sid)
        if not item:
            item = {"id": sid, "nome": d.servidor.nome, "periodos": []}
            impedidos_map[sid] = item

        tipo_label = getattr(d, "get_tipo_display", lambda: "Descanso")()
        ini = max(d.data_inicio, inicio)
        fim_ref = min(d.data_fim, fim)
        periodo_label = f"{ini:%d/%m}-{fim_ref:%d/%m}"
        motivo = f"{tipo_label} ({periodo_label})"
        obs = getattr(d, "observacoes", "")
        if obs:
            motivo = f"{motivo} - {obs}"
        if motivo not in item["periodos"]:
            item["periodos"].append(motivo)

    impedidos = list(impedidos_map.values())
    impedidos.sort(key=lambda x: str(x.get("nome") or "").lower())
    return JsonResponse({"mes": mes, "impedidos": impedidos})

def _parse_date(s: str) -> date | None:
    try:
        y, m, d = map(int, s.split("-"))
        return date(y, m, d)
    except Exception:
        return None

def _month_range_from_ym(ym: str) -> tuple[date, date] | None:
    try:
        year_str, month_str = (ym or "").split("-")
        year = int(year_str)
        month = int(month_str)
        if month < 1 or month > 12:
            return None
        last_day = monthrange(year, month)[1]
        return date(year, month, 1), date(year, month, last_day)
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
            { id?, meta_id, observacao, veiculo_id?, remarcado_de_id?, servidores_ids: [int,...] },
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
    dia = _parse_iso(str(iso))
    if not dia:
        return JsonResponse({"ok": False, "error": "Data invalida."}, status=400)

    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        return JsonResponse({"ok": False, "error": "Unidade nao definida."}, status=400)
    before_snapshot = snapshot_programacao_dia(unidade_id, dia)

    metas_permitidas = set(
        Meta.objects.filter(
            Q(alocacoes__unidade_id=unidade_id) | Q(unidade_criadora_id=unidade_id)
        )
        .values_list("id", flat=True)
        .distinct()
    )
    veiculos_permitidos = set(
        Veiculo.objects.filter(unidade_id=unidade_id).values_list("id", flat=True)
    )
    meta_expediente_id = getattr(settings, "META_EXPEDIENTE_ID", None)
    try:
        meta_expediente_id = int(meta_expediente_id) if meta_expediente_id is not None else None
    except (TypeError, ValueError):
        meta_expediente_id = None

    with transaction.atomic():
        prog = (
            Programacao.objects.select_for_update()
            .filter(data=dia, unidade_id=unidade_id)
            .first()
        )
        if not prog:
            prog = Programacao.objects.create(
                data=dia,
                unidade_id=unidade_id,
                observacao=body.get("observacao") or "",
                criado_por=getattr(request, "user", None),
            )

        if body.get("observacao") is not None:
            Programacao.objects.filter(pk=prog.pk).update(
                observacao=body.get("observacao") or ""
            )

        # itens já existentes
        existentes_qs = ProgramacaoItem.objects.filter(programacao=prog).select_related("programacao")
        existentes: Dict[int, ProgramacaoItem] = {pi.id: pi for pi in existentes_qs}
        existentes_servidores_por_item: Dict[int, set[int]] = {}
        if existentes:
            for item_id, servidor_id in ProgramacaoItemServidor.objects.filter(
                item_id__in=list(existentes.keys())
            ).values_list("item_id", "servidor_id"):
                existentes_servidores_por_item.setdefault(int(item_id), set()).add(int(servidor_id))

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
            if meta_id not in metas_permitidas:
                continue
            is_expediente = meta_expediente_id is not None and meta_id == meta_expediente_id

            obs = it.get("observacao") or ""
            raw_veiculo = it.get("veiculo_id")
            try:
                veiculo_id = int(raw_veiculo) if raw_veiculo not in (None, "", "null") else None
            except (TypeError, ValueError):
                veiculo_id = None
            if veiculo_id is not None and veiculo_id not in veiculos_permitidos:
                veiculo_id = None

            candidatos_servidores_ids: list[int] = []
            vistos_servidores: set[int] = set()
            for sid in (it.get("servidores_ids") or []):
                try:
                    sid_int = int(sid)
                except (TypeError, ValueError):
                    continue
                if sid_int in vistos_servidores:
                    continue
                vistos_servidores.add(sid_int)
                candidatos_servidores_ids.append(sid_int)

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

            remarcado_de_id = _resolve_remarcado_de_id(
                unidade_id=unidade_id,
                meta_id=meta_id,
                raw_value=it.get("remarcado_de_id"),
                ignore_item_id=item_id,
            )

            allowed_existing_ids = existentes_servidores_por_item.get(item_id or 0, set())
            servidores_ids: list[int] = []
            for sid_int in candidatos_servidores_ids:
                if ativos_ids and sid_int not in ativos_ids and sid_int not in allowed_existing_ids:
                    # Bloqueia novos vinculos com inativos, mas preserva vinculos historicos do proprio item.
                    continue
                servidores_ids.append(sid_int)

            # Ignora item vazio (exceto expediente): sem servidores, sem veiculo e sem observacao.
            if (not is_expediente) and (not servidores_ids) and veiculo_id is None and not obs:
                continue

            if pi:
                ProgramacaoItem.objects.filter(pk=pi.pk).update(
                    meta_id=meta_id,
                    observacao=obs,
                    veiculo_id=veiculo_id,
                    remarcado_de_id=remarcado_de_id if "remarcado_de_id" in it else getattr(pi, "remarcado_de_id", None),
                )
            else:
                pi = ProgramacaoItem.objects.create(
                    programacao=prog,
                    meta_id=meta_id,
                    observacao=obs,
                    veiculo_id=veiculo_id,
                    remarcado_de_id=remarcado_de_id,
                    concluido=False,
                )
                item_id = pi.id

            if item_id is None:
                continue

            ids_payload.add(item_id)

            # substitui vinculos de servidores
            ProgramacaoItemServidor.objects.filter(item_id=item_id).delete()
            if servidores_ids:
                bulk = [
                    ProgramacaoItemServidor(item_id=item_id, servidor_id=sid)
                    for sid in servidores_ids
                ]
                ProgramacaoItemServidor.objects.bulk_create(bulk)
                total_vinculos += len(bulk)
        # delete-orphans: remove itens que não vieram no payload
        orfaos = [
            pi_id
            for (pi_id, pi) in existentes.items()
            if pi_id not in ids_payload and (meta_expediente_id is None or int(getattr(pi, "meta_id", 0) or 0) != meta_expediente_id)
        ]
        if orfaos:
            ProgramacaoItemServidor.objects.filter(item_id__in=orfaos).delete()
            ProgramacaoItem.objects.filter(id__in=orfaos).delete()

        after_snapshot = snapshot_programacao_dia(unidade_id, dia)
        record_programacao_day_diff_after_commit(
            unidade_id=unidade_id,
            data_ref=dia,
            user=request.user,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            origem="modal",
        )

    return JsonResponse({
        "ok": True,
        "programacao_id": prog.id,
        "itens": len(ids_payload),
        "servidores_vinculados": total_vinculos,
    })

# antigo dummy de exclusão removido (substituído por excluir_programacao_secure)
# =============================================================================
# Helpers - datas
# =============================================================================
def _parse_iso(s: str) -> date | None:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _pick_plantao_id(request, ds: date | None, de: date | None) -> int | None:
    if not ds or not de:
        return None
    try:
        from plantao.models import Plantao  # type: ignore
    except Exception:
        return None

    unidade_id = get_unidade_atual_id(request)
    try:
        field_names = [f.name for f in Plantao._meta.fields]
    except Exception:
        field_names = []

    qs = Plantao.objects.filter(inicio__lte=de, fim__gte=ds)
    if ("unidade" in field_names or "unidade_id" in field_names) and unidade_id:
        qs = qs.filter(unidade_id=unidade_id)
    plantao_id = qs.order_by("-inicio", "-id").values_list("id", flat=True).first()
    return int(plantao_id) if plantao_id else None


def _pick_plantao_id_by_date(request, d_ref: date | None) -> int | None:
    if not d_ref:
        return None
    try:
        from plantao.models import Plantao  # type: ignore
    except Exception:
        return None

    unidade_id = get_unidade_atual_id(request)
    try:
        field_names = [f.name for f in Plantao._meta.fields]
    except Exception:
        field_names = []

    qs = Plantao.objects.filter(inicio__lte=d_ref, fim__gte=d_ref)
    if ("unidade" in field_names or "unidade_id" in field_names) and unidade_id:
        qs = qs.filter(unidade_id=unidade_id)
    plantao_id = qs.order_by("-inicio", "-id").values_list("id", flat=True).first()
    return int(plantao_id) if plantao_id else None


# =============================================================================
# Helpers - PLANTONISTAS (bridge + ORM + render)
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
    if not plantao_id:
        ds = _parse_iso(start)
        de = _parse_iso(end)
        plantao_id = _pick_plantao_id_by_date(request, de) or _pick_plantao_id(request, ds, de)
    if plantao_id:
        for c in combos:
            c["plantao_id"] = plantao_id

    ds = _parse_iso(start)
    de = _parse_iso(end)

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
                by_server: Dict[Any, Dict[str, Any]] = {}
                for sem in semanas:
                    sem_ini_raw = sem.get("inicio")
                    sem_fim_raw = sem.get("fim")
                    sem_ini = _parse_iso(str(sem_ini_raw or "")[:10]) if sem_ini_raw else None
                    sem_fim = _parse_iso(str(sem_fim_raw or "")[:10]) if sem_fim_raw else None
                    if sem_ini and ds and sem_ini < ds:
                        sem_ini = ds
                    if sem_fim and de and sem_fim > de:
                        sem_fim = de
                    periodo_label = ""
                    if sem_ini and sem_fim:
                        periodo_label = f"{sem_ini:%d/%m/%Y} a {sem_fim:%d/%m/%Y}"

                    for srv in (sem.get("servidores") or []):
                        sid = srv.get("id")
                        nome = (srv.get("nome") or srv.get("servidor") or "").strip()
                        tel = (srv.get("telefone") or "").strip()
                        key: Any = sid
                        if key is None:
                            key = (nome.casefold(), tel)

                        item = by_server.get(key)
                        if not item:
                            item = {"id": sid, "nome": nome, "telefone": tel, "periodos": []}
                            by_server[key] = item

                        if periodo_label and periodo_label not in item["periodos"]:
                            item["periodos"].append(periodo_label)

                out = list(by_server.values())
                out.sort(key=lambda x: str(x.get("nome") or "").lower())
                if out:
                    return out
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
        from plantao.models import SemanaServidor  # type: ignore
        unidade_id = get_unidade_atual_id(request)
        plantao_id = request.GET.get("plantao_id") or request.session.get("plantao_id")
        if not plantao_id:
            plantao_id = _pick_plantao_id_by_date(request, de) or _pick_plantao_id(request, ds, de)

        ss_qs = (
            SemanaServidor.objects
            .select_related("servidor", "semana", "semana__plantao")
            .filter(
                servidor__ativo=True,
                semana__inicio__lte=de,
                semana__fim__gte=ds,
                semana__plantao__inicio__lte=de,
                semana__plantao__fim__gte=ds,
            )
        )
        if plantao_id:
            ss_qs = ss_qs.filter(semana__plantao_id=plantao_id)
        if unidade_id:
            try:
                ss_qs = ss_qs.filter(semana__plantao__unidade_id=unidade_id)
            except Exception:
                ss_qs = ss_qs.filter(servidor__unidade_id=unidade_id)

        ss_qs = ss_qs.order_by("servidor__nome", "semana__inicio", "ordem", "id")

        by_server: Dict[Any, Dict[str, Any]] = {}
        for ss in ss_qs:
            servidor = getattr(ss, "servidor", None)
            sid = getattr(servidor, "id", None)
            nome = (getattr(servidor, "nome", "") or "").strip()
            tel = (getattr(ss, "telefone_snapshot", "") or "").strip()
            key: Any = sid if sid is not None else (nome.casefold(), tel)

            item = by_server.get(key)
            if not item:
                item = {"id": sid, "nome": nome, "telefone": tel, "periodos": []}
                by_server[key] = item

            sem = getattr(ss, "semana", None)
            sem_ini = getattr(sem, "inicio", None)
            sem_fim = getattr(sem, "fim", None)
            plantao = getattr(sem, "plantao", None)
            plantao_ini = getattr(plantao, "inicio", None)
            plantao_fim = getattr(plantao, "fim", None)
            if sem_ini and sem_fim:
                ini = sem_ini if sem_ini >= ds else ds
                fim = sem_fim if sem_fim <= de else de
                if plantao_ini and ini < plantao_ini:
                    ini = plantao_ini
                if plantao_fim and fim > plantao_fim:
                    fim = plantao_fim
                if fim < ini:
                    continue
                periodo_label = f"{ini:%d/%m/%Y} a {fim:%d/%m/%Y}"
                if periodo_label not in item["periodos"]:
                    item["periodos"].append(periodo_label)

        out = list(by_server.values())
        out.sort(key=lambda x: str(x.get("nome") or "").lower())
        return out
    except Exception:
        return []


def _render_plantonistas_html(servidores: List[Dict[str, Any]], start: str, end: str) -> str:
    esc = lambda s: html.escape(str(s or ""))
    start_br = _format_iso_to_br(start)
    end_br = _format_iso_to_br(end)
    ds = _parse_iso(start)
    de = _parse_iso(end)
    titulo = "Plantonista da semana"
    if ds and de and (de - ds).days >= 7:
        titulo = "Plantonistas no periodo"
    show_item_period = titulo != "Plantonista da semana"

    def _phone_display(raw: str) -> str:
        val = (raw or "").strip()
        if not val:
            return ""
        if "(" in val or ")" in val:
            return val
        return f"({val})"

    header = (
        '<h6 class="fw-semibold mb-2">'
        '<span class="badge bg-light border me-2">'
        '<i class="bi bi-person-badge text-primary"></i></span>'
        f"{esc(titulo)}"
        "</h6>"
    )
    if not servidores:
        return header + '<div class="text-muted">Nenhum plantonista encontrado para o periodo.</div>'

    items = []
    for s in servidores:
        nome = esc(s.get("nome") or s.get("servidor") or "")
        tel = s.get("telefone")
        tel_disp = _phone_display(str(tel or ""))
        tel_html = f' <span class="text-muted">- {esc(tel_disp)}</span>' if tel_disp else ""

        periodo_suffix = ""
        if show_item_period:
            periodos = s.get("periodos") or []
            periodos_fmt = []
            for p in periodos:
                p_txt = str(p or "").strip()
                if p_txt and p_txt not in periodos_fmt:
                    periodos_fmt.append(p_txt)
            if not periodos_fmt and start_br and end_br:
                periodos_fmt.append(f"{start_br} a {end_br}")

            if periodos_fmt:
                periodo_suffix = f" <span class='text-muted'>- de {esc('; de '.join(periodos_fmt))}</span>"

        items.append(f"<li><span class='fw-semibold'>{nome}</span>{tel_html}{periodo_suffix}</li>")

    return header + f'<ul class="mb-0">{"".join(items)}</ul>'

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
            .filter(item_id__in=item_ids)
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
            "observacao": (getattr(it, "observacao", "") or "").strip(),
            "meta_descricao": (getattr(meta, "descricao", "") or "").strip() if meta else "",
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

    livres, impedidos, _feriados, _plantao = _servidores_status_para_data(unidade_id, dia)

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
            return "<span class='text-muted'>-</span>"
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

        feriados_do_dia = feriados_map.get(dt) or []
        is_feriado = bool(feriados_do_dia)

        if is_feriado:
            # Em feriados, nao exibir expediente administrativo no relatorio.
            expediente = []
            expediente_extra = []
        else:
            # Mescla expediente calculado + do legado (sem duplicar nomes)
            if expediente_extra:
                seen = set()
                exp_merge = []
                for nome in list(expediente) + expediente_extra:
                    if nome not in seen:
                        seen.add(nome)
                        exp_merge.append(nome)
                expediente = exp_merge

        # Monta os blocks garantindo feriados/expediente primeiro
        blocks: list[dict] = []
        if feriados_do_dia:
            blocks.append({"kind": "feriado", "descricoes": feriados_do_dia})
        if expediente and not is_feriado:
            blocks.append({"kind": "expediente", "servidores": expediente})
        for it in itens_atividades:
            blocks.append({
                "kind": "atividade",
                "meta": it["meta"],
                "servidores": it["servidores"],
                "veiculo": it["veiculo"],
                "observacao": it.get("observacao") or "",
                "meta_descricao": it.get("meta_descricao") or "",
            })
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
                    + "<td class='veiculo-cell text-nowrap'>-</td>"
                    + "<td class='realizada-cell'>-</td>"
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
                            "observacao": b.get("observacao") or "",
                        })

                obs_txt = (b.get("observacao") or "").strip()
                obs_html = (
                    f"<div class='atividade-obs'>Obs.: {html.escape(obs_txt)}</div>"
                    if obs_txt else ""
                )
                meta_desc_txt = (b.get("meta_descricao") or "").strip()
                meta_desc_html = (
                    f"<div class='text-muted fst-italic mt-1'>Obs: {html.escape(meta_desc_txt)}</div>"
                    if meta_desc_txt else ""
                )
                day_rows.append(
                    open_tr
                    + dia_td
                    + f"<td class='atividade-cell'><div class='atividade-main'>{html.escape(b['meta'])}</div>{obs_html}</td>"
                    + f"<td>{_srv_list_html(b['servidores'], with_boxes=True, inline=False)}{meta_desc_html}</td>"
                    + f"<td class='veiculo-cell text-nowrap'>{html.escape(b['veiculo'])}</td>"
                    + f"<td class='realizada-cell'>{_realizada_boxes()}</td>"
                    + "</tr>"
                )

            else:  # impedidos
                imp_lines = "".join(
                    f"<div class='text-muted'><span class='fw-semibold'>{html.escape(i['nome'])}</span>"
                    f" - {html.escape(i['motivo'])}</div>"
                    for i in b["dados"]
                )
                if not imp_lines:
                    imp_lines = "<span class='text-muted'>-</span>"
                day_rows.append(
                    open_tr
                    + dia_td
                    + "<td class='atividade-cell'><em>Impedidos</em></td>"
                    + f"<td>{imp_lines}</td>"
                    + "<td class='veiculo-cell text-nowrap'>-</td>"
                    + "<td class='realizada-cell'>-</td>"
                    + "</tr>"
                )

        # empacota o DIA num <tbody> próprio (anti quebra)
        bodies_html.append("<tbody class='dia-bucket'>" + "".join(day_rows) + "</tbody>")

    # ---------- CSS embutido ----------
    style = (
        "<style>"
        "/* ====== RELATORIO ====== */"
        ".report-container{ max-width:1200px; margin-left:auto; margin-right:auto; padding:0 0.5rem; }"
        ".report-toolbar{ display:flex; align-items:center; gap:.35rem; }"
        ".report-toolbar .btn{ min-width:110px; }"
        ".report-toolbar .btn i{ margin-right:.35rem; }"
        "/* ====== TELA ====== */"
        ".programacao-semana-table .feriado-desc{ color:#842029; font-weight:600; }"
        ".programacao-semana-table tbody td.veiculo-cell{"
        "  text-align:center !important; vertical-align:middle !important;"
        "}"
        ".programacao-semana-table tbody tr:not(.day-end) > td{"
        "  border-bottom: 1px solid #d7dee8 !important;"
        "}"
        ".programacao-semana-table tbody tr.day-end > td,"
        ".programacao-semana-table tbody td.dia-cell.day-end{"
        "  border-bottom: 2px solid #6c757d !important;"
        "}"
        ".programacao-semana-table th.col-dia, .programacao-semana-table td.dia-cell{ min-width:110px; width:110px; }"
        ".programacao-semana-table th.col-veiculo, .programacao-semana-table td.veiculo-cell{ min-width:120px; width:120px; }"
        ".programacao-semana-table th.col-realizada, .programacao-semana-table td.realizada-cell{ min-width:100px; width:100px; }"
        ".programacao-semana-table th.col-veiculo, .programacao-semana-table th.col-realizada{ white-space:nowrap; }"
        ".programacao-semana-table td, .programacao-semana-table th{ vertical-align: top; }"
        ".programacao-semana-table .atividade-main{ font-weight:600; }"
        ".programacao-semana-table .atividade-obs{ display:block; margin-top:.15rem; font-style:italic; font-size:.82em; line-height:1.25; color:#6c757d; }"

        "/* Relatório 'Justificativa' */"
        ".rel-atividades .card-ativ{ page-break-inside: avoid; }"
        ".rel-atividades .mini-table{ width:100%; border-collapse:collapse; }"
        ".rel-atividades .mini-table td{ border:1px solid var(--bs-border-color); padding:.35rem .5rem; }"
        ".rel-atividades .mini-table .lbl{ width:180px; white-space:nowrap; }"
        ".rel-atividades .mini-table .just{ height:2.2rem; }"
        ".rel-atividades .servidor-title{ font-weight:600; margin-bottom:.35rem; }"
        ".rel-atividades .atividade-obs{ display:block; margin-top:.15rem; font-style:italic; font-size:.9em; line-height:1.25; color:#6c757d; }"

        "/* ====== IMPRESSAO ====== */"
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
        "  .programacao-semana-table th.col-dia, .programacao-semana-table td.dia-cell{"
        "    min-width: 90px !important; width: 90px !important;"
        "  }"
        "  .programacao-semana-table th.col-veiculo, .programacao-semana-table td.veiculo-cell{"
        "    min-width: 120px !important; width: 120px !important;"
        "  }"
        "  .programacao-semana-table th.col-realizada, .programacao-semana-table td.realizada-cell{"
        "    min-width: 100px !important; width: 100px !important;"
        "  }"
        "  .print-cbx{ width:10px; height:10px; margin:0 3px 0 4px; border-width:1.2px; }"
        "  .programacao-semana-table thead th{"
        "    border-bottom: 0.75pt solid #000 !important;"
        "    border-top: 0.5pt solid #000 !important;"
        "  }"
        "  .programacao-semana-table tbody tr:not(.day-end) > td{"
        "    border-bottom: 0.6pt solid #d7dee8 !important;"
        "  }"
        "  .programacao-semana-table tbody tr.day-end > td,"
        "  .programacao-semana-table tbody td.dia-cell.day-end{"
        "    border-bottom: 1.4pt solid #495057 !important;"
        "  }"
        "  .rel-atividades .mini-table td{ padding:.25rem .35rem !important; }"
        "  .rel-atividades .just{ display:inline-block; width:100%; min-height:14px; border-bottom:1px solid #000; }"
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
        "<th class='col-dia'>Dia</th>"
        "<th class='col-atividade'>Atividade</th>"
        "<th class='col-servidores'>Servidores</th>"
        "<th class='col-veiculo'>Veículo</th>"
        "<th class='col-realizada'>Realizada</th>"
        "</tr>"
        "</thead>"
        + "".join(bodies_html) +  # <<< vários <tbody>, um por dia
        "</table></div>"
        + (""
           if any(bodies_html) else
           "<div class='text-muted mt-2'>Nenhuma atividade nesta semana.</div>")
        + "</div>"
    )

    # ---------- RELATORIO DE ATIVIDADES (embaixo) ----------
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
            obs_txt = (it.get("observacao") or "").strip()
            obs_html = f"<div class='atividade-obs'>Obs.: {html.escape(obs_txt)}</div>" if obs_txt else ""

            # 1ª linha: dia + atividade
            linhas.append(
                "<tr>"
                "<td class='lbl'>Dia</td>"
                f"<td>{dia}" + (f": {atividade}" if atividade else "") + obs_html + "</td>"
                "</tr>"
            )
            # 2a linha: apenas "Justificativa" com linha
            linhas.append(
                "<tr>"
                "<td class='lbl'>Justificativa</td>"
                "<td>"
                "<span class='just d-inline-block'></span>"
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
def _relatorio_observacao_from_request(request) -> str:
    try:
        raw = request.GET.get("observacao", "")
    except Exception:
        raw = ""
    obs = str(raw or "")
    obs = obs.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(obs) > 2000:
        obs = obs[:2000].rstrip()
    return obs


def _render_relatorio_observacao_html(observacao: str) -> str:
    obs = (observacao or "").strip()
    if not obs:
        return ""
    safe = html.escape(obs).replace("\n", "<br>")
    return f"""
      <div class="mt-3 px-3 pb-3">
        <div class="border rounded p-3 bg-light">
          <div class="small text-uppercase text-muted fw-semibold mb-1">Observação</div>
          <div class="small">{safe}</div>
        </div>
      </div>
    """


@login_required
@require_GET
def relatorios_parcial(request):
    start = request.GET.get("start", "")
    end = request.GET.get("end", "")
    observacao = _relatorio_observacao_from_request(request)
    observacao_html = _render_relatorio_observacao_html(observacao)

    # ORM primeiro: garante periodos por servidor de forma consistente no relatorio mensal.
    servidores = _fetch_plantonistas_via_orm(request, start, end)
    if not servidores:
        servidores = _fetch_plantonistas_via_bridge(request, start, end)

    plantonistas_html = _render_plantonistas_html(servidores, start, end)
    tabela_semana_html = _render_programacao_semana_html(request, start, end)
    period_label = _period_label_br(start, end)

    html_out = f"""
    <div id="relatorioPrintArea" class="card border-0 shadow-sm">
      <div class="card-body">
        <div class="container mt-3 report-container px-0">
          <div class="d-flex justify-content-between align-items-center mb-3">
            <h2 class="mb-0">
              <i class="bi bi-list-check me-2"></i> Programação de atividades
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
              {observacao_html}
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
            {observacao_html}
          </div>
        </div>
        """
    return JsonResponse({"ok": True, "html": html_out})


@login_required
@require_GET
def print_relatorio_semana(request):
    start = request.GET.get("start", "")
    end = request.GET.get("end", "")
    observacao = _relatorio_observacao_from_request(request)
    observacao_html = _render_relatorio_observacao_html(observacao)

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

    servidores = _fetch_plantonistas_via_orm(request, start, end)
    if not servidores:
        servidores = _fetch_plantonistas_via_bridge(request, start, end)

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
    @page{{ size:A4 landscape; margin:8mm; }}
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
        {observacao_html}
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
    observacao = _relatorio_observacao_from_request(request)
    observacao_html = _render_relatorio_observacao_html(observacao)

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
    @page{{ size:A4 portrait; margin:8mm; }}
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
        {observacao_html}
      </div>
    </div>
  </div>
</body>
</html>"""
    return HttpResponse(html_out)


# (Opcional) endpoint dummy para manter compatibilidade em dev
@login_required
@require_GET
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
        # FullCalendar envia "end" exclusivo para eventos all-day.
        qs = qs.filter(data__lt=end_date)

    programacoes = list(qs.values("id", "data", "concluida"))
    prog_ids = [p["id"] for p in programacoes]
    counts: Dict[int, Dict[str, int]] = {
        pid: {"total": 0, "concluidas": 0, "nao_realizadas": 0}
        for pid in prog_ids
    }
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
                nao_realizadas=Count("id", filter=Q(concluido=False, concluido_em__isnull=False)),
            )
        )
        for row in itens_stats:
            pid = row.get("programacao_id")
            if pid in counts:
                counts[pid] = {
                    "total": int(row.get("total") or 0),
                    "concluidas": int(row.get("concluidas") or 0),
                    "nao_realizadas": int(row.get("nao_realizadas") or 0),
                }
        title_counts: Dict[int, Dict[str, int]] = {pid: {} for pid in prog_ids}
        title_order: Dict[int, list[str]] = {pid: [] for pid in prog_ids}
        activity_counts: Dict[int, Dict[tuple[str, str], int]] = {pid: {} for pid in prog_ids}
        activity_order: Dict[int, list[tuple[str, str]]] = {pid: [] for pid in prog_ids}
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
            if titulo not in title_counts[pid]:
                title_counts[pid][titulo] = 0
                title_order[pid].append(titulo)
            title_counts[pid][titulo] += 1

            status_item = _item_execucao_status_from_fields(
                bool(getattr(item, "concluido", False)),
                getattr(item, "concluido_em", None),
                bool(getattr(item, "nao_realizada_justificada", False)),
                getattr(item, "remarcado_de_id", None),
            )
            key = (titulo, status_item)
            if key not in activity_counts[pid]:
                activity_counts[pid][key] = 0
                activity_order[pid].append(key)
            activity_counts[pid][key] += 1

        for pid in prog_ids:
            for titulo in title_order[pid]:
                count = title_counts[pid].get(titulo, 0)
                label = f"{titulo} ({count})" if count > 1 else titulo
                metas_por_programacao[pid].append(label)
            for key in activity_order[pid]:
                titulo, status_item = key
                count = activity_counts[pid].get(key, 0)
                atividades_por_programacao[pid].append({
                    "titulo": titulo,
                    "status": status_item,
                    "quantidade": count,
                })

    data = []
    for prog in programacoes:
        pid = prog["id"]
        contadores = counts.get(pid, {"total": 0, "concluidas": 0, "nao_realizadas": 0})
        total = contadores["total"]
        if total == 0:
            continue
        concluidas = contadores["concluidas"]
        nao_realizadas = contadores.get("nao_realizadas", 0)
        pendentes = max(total - concluidas - nao_realizadas, 0)

        nome_atividades = metas_por_programacao.get(pid) or []
        nome_titulo = "; ".join(nome_atividades) if nome_atividades else ""
        total_label = f"{total} atividade{'s' if total != 1 else ''}"
        concluidas_label = f"{concluidas} concluida{'s' if concluidas != 1 else ''}"
        nao_realizadas_label = f"{nao_realizadas} não realizada{'s' if nao_realizadas != 1 else ''}"
        pendentes_label = f"{pendentes} pendente{'s' if pendentes != 1 else ''}"
        title = nome_titulo or f"({total_label} | {concluidas_label} | {nao_realizadas_label} | {pendentes_label})"
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
                "total_nao_realizadas": nao_realizadas,
                "total_pendentes": pendentes,
                "nomes_atividades": nome_atividades,
                "atividades": atividades_por_programacao.get(pid, []),
            },
        })
    return JsonResponse(data, safe=False)


@login_required
@require_GET
def metas_disponiveis(request):
    """
    Metas disponiveis para a unidade atual no modal de programacao.
    Inclui:
    - metas alocadas para a unidade;
    - metas criadas na unidade sem nenhuma alocacao ainda.
    """
    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        return JsonResponse({"metas": []})

    atividade_id = request.GET.get("atividade")
    meta_status_filter = (request.GET.get("meta_status") or "").strip().lower()
    if meta_status_filter not in {"andamento", "atrasada", "concluida", "encerrada"}:
        meta_status_filter = ""
    only_encerradas = meta_status_filter == "encerrada"
    include_all_status = meta_status_filter == ""
    only_nao_encerradas = meta_status_filter in {"andamento", "atrasada", "concluida"}
    data_ref = _parse_date((request.GET.get("data") or "").strip())
    today = timezone.localdate()
    reference_month_start = (data_ref or today).replace(day=1)
    metas_com_itens_abertos_ids = (
        _meta_ids_com_itens_abertos(
            unidade_id,
            reference_month_start=reference_month_start,
        )
        if data_ref
        else set()
    )
    qs = (
        MetaAlocacao.objects
        .select_related("meta", "meta__atividade")
        .filter(unidade_id=unidade_id)
        .order_by("meta__data_limite", "meta__titulo")
    )
    if only_encerradas:
        qs = qs.filter(meta__encerrada=True)
    elif only_nao_encerradas:
        qs = qs.filter(meta__encerrada=False)
    if atividade_id:
        qs = qs.filter(meta__atividade_id=atividade_id)
    if data_ref and not only_encerradas:
        # Mantemos metas com data limite futura e tambem metas vencidas que ainda
        # tenham itens pendentes/nao realizadas, para que continuem nos meses seguintes.
        q_periodo = (
            Q(meta__data_limite__isnull=True)
            | Q(meta__data_limite__gte=data_ref)
            | Q(meta_id__in=metas_com_itens_abertos_ids)
        )
        if include_all_status:
            q_periodo = Q(meta__encerrada=True) | q_periodo
        qs = qs.filter(q_periodo)

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
            limite_meta = getattr(meta, "data_limite", None)
            if limite_meta and hasattr(limite_meta, "date") and not isinstance(limite_meta, date):
                limite_meta = limite_meta.date()
            bucket[mid] = {
                "id": mid,
                "nome": getattr(meta, "display_titulo", None) or getattr(meta, "titulo", "(sem título)"),
                "descricao": (getattr(meta, "descricao", "") or "").strip(),
                "atividade_nome": atividade_nome,
                "data_inicio": getattr(meta, "data_inicio", None),
                "data_limite": getattr(meta, "data_limite", None),
                "alocado_unidade": 0,
                "executado_unidade": 0,
                "meta_total": int(getattr(meta, "quantidade_alvo", 0) or 0),
                "status": status_key,
                "status_label": status_label,
                "carry_forward": bool(
                    data_ref
                    and limite_meta
                    and limite_meta < reference_month_start
                    and mid in metas_com_itens_abertos_ids
                ),
            }
        bucket[mid]["alocado_unidade"] += int(getattr(al, "quantidade_alocada", 0) or 0)
        try:
            prog_sum = al.progresso.aggregate(total=Sum("quantidade")).get("total") or 0
        except Exception:
            prog_sum = 0
        bucket[mid]["executado_unidade"] += int(prog_sum)
        bucket[mid].setdefault("programadas_total", 0)

    metas_sem_alocacao_qs = (
        Meta.objects
        .select_related("atividade")
        .filter(unidade_criadora_id=unidade_id, alocacoes__isnull=True)
        .order_by("data_limite", "titulo")
    )
    if only_encerradas:
        metas_sem_alocacao_qs = metas_sem_alocacao_qs.filter(encerrada=True)
    elif only_nao_encerradas:
        metas_sem_alocacao_qs = metas_sem_alocacao_qs.filter(encerrada=False)
    if atividade_id:
        metas_sem_alocacao_qs = metas_sem_alocacao_qs.filter(atividade_id=atividade_id)
    if data_ref and not only_encerradas:
        q_periodo_sem_aloc = (
            Q(data_limite__isnull=True)
            | Q(data_limite__gte=data_ref)
            | Q(id__in=metas_com_itens_abertos_ids)
        )
        if include_all_status:
            q_periodo_sem_aloc = Q(encerrada=True) | q_periodo_sem_aloc
        metas_sem_alocacao_qs = metas_sem_alocacao_qs.filter(q_periodo_sem_aloc)

    for meta in metas_sem_alocacao_qs:
        if not getattr(meta, "id", None):
            continue
        mid = int(meta.id)
        if mid in bucket:
            continue
        atividade = getattr(meta, "atividade", None)
        atividade_nome = None
        if atividade:
            atividade_nome = getattr(atividade, "titulo", None) or getattr(atividade, "nome", None)
        status_key, status_label = _meta_status_info(meta)
        limite_meta = getattr(meta, "data_limite", None)
        if limite_meta and hasattr(limite_meta, "date") and not isinstance(limite_meta, date):
            limite_meta = limite_meta.date()
        bucket[mid] = {
            "id": mid,
            "nome": getattr(meta, "display_titulo", None) or getattr(meta, "titulo", "(sem titulo)"),
            "descricao": (getattr(meta, "descricao", "") or "").strip(),
            "atividade_nome": atividade_nome,
            "data_inicio": getattr(meta, "data_inicio", None),
            "data_limite": getattr(meta, "data_limite", None),
            "alocado_unidade": 0,
            "executado_unidade": 0,
            "meta_total": int(getattr(meta, "quantidade_alvo", 0) or 0),
            "status": status_key,
            "status_label": status_label,
            "carry_forward": bool(
                data_ref
                and limite_meta
                and limite_meta < reference_month_start
                and mid in metas_com_itens_abertos_ids
            ),
            "programadas_total": 0,
        }

    metas_cadastradas_qs = Meta.objects.filter(
        Q(alocacoes__unidade_id=unidade_id) |
        Q(unidade_criadora_id=unidade_id, alocacoes__isnull=True)
    ).distinct()
    if atividade_id:
        metas_cadastradas_qs = metas_cadastradas_qs.filter(atividade_id=atividade_id)
    earliest_month_by_year: Dict[str, str] = {}
    for row in metas_cadastradas_qs.exclude(data_limite__isnull=True).values_list("data_limite", flat=True):
        if not row:
            continue
        year_key = str(getattr(row, "year", ""))
        month_key = f"{row.year}-{row.month:02d}"
        if year_key and (year_key not in earliest_month_by_year or month_key < earliest_month_by_year[year_key]):
            earliest_month_by_year[year_key] = month_key

    meta_ids = list(bucket.keys())
    if meta_ids:
        itens_stats = (
            ProgramacaoItem.objects
            .filter(meta_id__in=meta_ids, programacao__unidade_id=unidade_id)
            .values("meta_id")
            .annotate(
                total=Count("id"),
                nao_realizadas_atrasadas=Count(
                    "id",
                    filter=Q(
                        concluido=False,
                        concluido_em__isnull=False,
                        nao_realizada_justificada=False,
                        programacao__data__lt=reference_month_start,
                        meta__data_limite__isnull=False,
                        meta__data_limite__lt=reference_month_start,
                    ),
                ),
                pendentes_atrasadas=Count(
                    "id",
                    filter=Q(concluido=False, concluido_em__isnull=True, programacao__data__lt=today),
                ),
            )
        )
        for row in itens_stats:
            mid = int(row.get("meta_id") or 0)
            if mid in bucket:
                bucket[mid]["programadas_total"] = int(row.get("total") or 0)
                if (
                    bucket[mid].get("status") == "andamento"
                    and (
                        int(row.get("nao_realizadas_atrasadas") or 0) > 0
                        or int(row.get("pendentes_atrasadas") or 0) > 0
                    )
                ):
                    bucket[mid]["status"] = "atrasada"
                    bucket[mid]["status_label"] = "Atrasada"

    metas = list(bucket.values())
    if meta_status_filter:
        metas = [
            item for item in metas
            if str(item.get("status") or "").strip().lower() == meta_status_filter
        ]
    metas.sort(
        key=lambda x: (
            x.get("data_limite") is None,
            x.get("data_limite") or date.max,
            str(x.get("nome") or "").lower(),
        )
    )
    return JsonResponse({
        "metas": metas,
        "earliest_month_by_year": earliest_month_by_year,
    })


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

    itens_qs = list(
        ProgramacaoItem.objects.filter(programacao=prog).values(
            "id",
            "meta_id",
            "observacao",
            "veiculo_id",
            "remarcado_de_id",
            "concluido",
            "concluido_em",
            "nao_realizada_justificada",
        )
    )
    meta_ids: set[int] = set()
    for it in itens_qs:
        raw_meta_id = it.get("meta_id")
        try:
            if raw_meta_id is not None:
                meta_ids.add(int(raw_meta_id))
        except Exception:
            continue

    meta_title_by_id: Dict[int, str] = {}
    if meta_ids:
        metas_qs = Meta.objects.filter(id__in=list(meta_ids)).select_related("atividade")
        for meta in metas_qs:
            titulo = (
                getattr(meta, "display_titulo", None)
                or getattr(meta, "titulo", None)
                or ""
            )
            if not titulo:
                atividade = getattr(meta, "atividade", None)
                if atividade:
                    titulo = (
                        getattr(atividade, "titulo", None)
                        or getattr(atividade, "nome", None)
                        or ""
                    )
            titulo = str(titulo).strip() if titulo else ""
            if titulo:
                try:
                    meta_title_by_id[int(meta.id)] = titulo
                except Exception:
                    continue

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

    meta_expediente_id = getattr(settings, "META_EXPEDIENTE_ID", None)
    try:
        meta_expediente_id = int(meta_expediente_id) if meta_expediente_id is not None else None
    except (TypeError, ValueError):
        meta_expediente_id = None
    today = timezone.localdate()

    itens: List[Dict[str, Any]] = []
    for it in itens_qs:
        meta_id = it["meta_id"]
        iid = int(it["id"])
        concluido_db = bool(it.get("concluido"))
        concluido_em = it.get("concluido_em")
        nao_realizada_justificada = bool(it.get("nao_realizada_justificada"))
        remarcado_de_id = it.get("remarcado_de_id")
        auto_concluida_expediente = is_auto_concluida_expediente(
            meta_id=meta_id,
            meta_expediente_id=meta_expediente_id,
            programacao_data=dia,
            concluido=concluido_db,
            concluido_em=concluido_em,
            nao_realizada_justificada=nao_realizada_justificada,
            today=today,
        )
        status_execucao = EXECUTADA if auto_concluida_expediente else _item_execucao_status_from_fields(
            concluido_db,
            concluido_em,
            nao_realizada_justificada,
            remarcado_de_id,
        )
        obj = {
            "id": iid,
            "meta_id": meta_id,
            "observacao": it.get("observacao") or "",
            "veiculo_id": it.get("veiculo_id"),
            "remarcado_de_id": remarcado_de_id,
            "concluido": bool(concluido_db or auto_concluida_expediente),
            "status_execucao": status_execucao,
            "servidores_ids": serv_ids_by_item.get(iid, []),
            "servidores": serv_objs_by_item.get(iid, []),
        }
        try:
            if meta_id is not None:
                mid = int(meta_id)
                obj["titulo"] = meta_title_by_id.get(mid) or f"Meta #{mid}"
        except Exception:
            pass
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
    data_ref = getattr(prog, "data", None)
    before_snapshot = snapshot_programacao_dia(unidade_id, data_ref) if data_ref else None

    with transaction.atomic():
        prog_locked = (
            Programacao.objects.select_for_update()
            .filter(pk=prog.pk, unidade_id=unidade_id)
            .first()
        )
        if not prog_locked:
            return JsonResponse({"ok": True, "deleted": False})
        prog_locked.delete()
        after_snapshot = snapshot_programacao_dia(unidade_id, data_ref) if data_ref else None
        if data_ref:
            record_programacao_day_diff_after_commit(
                unidade_id=unidade_id,
                data_ref=data_ref,
                user=request.user,
                before_snapshot=before_snapshot,
                after_snapshot=after_snapshot,
                origem="exclusao",
            )
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

    with transaction.atomic():
        try:
            pi = (
                ProgramacaoItem.objects
                .select_for_update()
                .select_related("programacao")
                .get(pk=item_id, programacao__unidade_id=unidade_id)
            )
        except ProgramacaoItem.DoesNotExist:
            return JsonResponse({"ok": False, "error": "Item não encontrado."}, status=404)
        data_ref = getattr(getattr(pi, "programacao", None), "data", None)
        before_snapshot = snapshot_programacao_dia(unidade_id, data_ref) if data_ref else None

        if realizada:
            pi.concluido = True
            pi.concluido_em = timezone.now()
            pi.nao_realizada_justificada = False
            pi.concluido_por_id = getattr(request.user, "id", None)
        else:
            # No toggle rapido, "desmarcar" volta para pendente.
            pi.concluido = False
            pi.concluido_em = None
            pi.nao_realizada_justificada = False
            pi.concluido_por_id = None
        pi.save(update_fields=["concluido", "concluido_em", "nao_realizada_justificada", "concluido_por_id"])
        after_snapshot = snapshot_programacao_dia(unidade_id, data_ref) if data_ref else None
        if data_ref:
            record_programacao_day_diff_after_commit(
                unidade_id=unidade_id,
                data_ref=data_ref,
                user=request.user,
                before_snapshot=before_snapshot,
                after_snapshot=after_snapshot,
                origem="status_toggle",
            )

    return JsonResponse({"ok": True, "item_id": pi.id, "realizada": pi.concluido})


def _item_execucao_status(item: ProgramacaoItem) -> str:
    return _item_execucao_status_from_fields(
        bool(getattr(item, "concluido", False)),
        getattr(item, "concluido_em", None),
        bool(getattr(item, "nao_realizada_justificada", False)),
        getattr(item, "remarcado_de_id", None),
    )


def _item_execucao_status_from_fields(
    concluido: bool,
    concluido_em,
    nao_realizada_justificada: bool = False,
    remarcado_de_id: int | None = None,
) -> str:
    return item_execucao_status_from_fields(
        concluido,
        concluido_em,
        nao_realizada_justificada,
        remarcado_de_id,
    )


@login_required
@require_http_methods(["GET", "POST"])
@csrf_protect
def concluir_item_form(request, item_id: int):
    """Permite marcar um item da programacao como realizado ou nao com observacao."""
    unidade_ctx_id = get_unidade_atual_id(request)
    if not unidade_ctx_id:
        messages.error(request, "Unidade nao definida no contexto.")
        return redirect("minhas_metas:minhas_metas")

    try:
        pi = (
            ProgramacaoItem.objects
            .select_related("programacao", "meta", "veiculo")
            .get(pk=item_id, programacao__unidade_id=unidade_ctx_id)
        )
    except ProgramacaoItem.DoesNotExist:
        messages.error(request, "Item nao encontrado para a unidade atual.")
        return redirect("minhas_metas:minhas_metas")
    prog = pi.programacao
    unidade_id = getattr(prog, "unidade_id", None)
    meta = pi.meta
    source_context = (request.GET.get("source") or request.POST.get("source") or "").strip().lower()
    ignorar_pendentes = source_context == "minhas-metas"

    links = (
        ProgramacaoItemServidor.objects
        .select_related("servidor")
        .filter(item_id=pi.id)
        .order_by("servidor__nome")
    )
    servidores = [getattr(l.servidor, "nome", f"Servidor {l.servidor_id}") for l in links]

    meta = getattr(pi, "meta", None)
    programacao = pi.programacao
    remarcacao_opcoes = _build_remarcacao_opcoes(unidade_id=unidade_ctx_id, item=pi)
    remarcado_de_current_id = _resolve_remarcado_de_id(
        unidade_id=unidade_ctx_id,
        meta_id=getattr(meta, "id", None),
        raw_value=getattr(pi, "remarcado_de_id", None),
        ignore_item_id=pi.id,
    )
    if remarcado_de_current_id is None and remarcacao_opcoes:
        remarcado_de_current_id = remarcacao_opcoes[0]["id"]
    permite_status_remarcado = bool(remarcacao_opcoes or remarcado_de_current_id)

    pendentes_qs = ProgramacaoItem.objects.none()
    pendentes_total = 0
    pendentes_preview: list[dict[str, Any]] = []
    pendentes_tem_mais = False
    if (not ignorar_pendentes) and meta and getattr(meta, "id", None):
        pendentes_qs = (
            ProgramacaoItem.objects
            .select_related("programacao", "veiculo")
            .filter(
                meta_id=meta.id,
                programacao__unidade_id=unidade_ctx_id,
                concluido=False,
                concluido_em__isnull=True,
            )
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
        form_errors: dict[str, str] = {}
        status_execucao = (request.POST.get("status_execucao") or "").strip().lower()
        if status_execucao not in {EXECUTADA, REMARCADA_CONCLUIDA, NAO_REALIZADA, NAO_REALIZADA_JUSTIFICADA, PENDENTE}:
            # Compatibilidade com payload legado (checkbox "realizado").
            realizado_raw = (request.POST.get("realizado") or "").strip().lower()
            status_execucao = EXECUTADA if realizado_raw in {"1", "true", "on", "sim"} else PENDENTE

        concluido_flag = status_execucao in {EXECUTADA, REMARCADA_CONCLUIDA}
        marcado_com_status = status_execucao in {EXECUTADA, REMARCADA_CONCLUIDA, NAO_REALIZADA, NAO_REALIZADA_JUSTIFICADA}
        obs_final = (request.POST.get("observacoes") or "").strip()
        confirmar_pendentes = (request.POST.get("confirmar_pendentes") or "").strip() == "1"
        remarcado_de_selected_id = _resolve_remarcado_de_id(
            unidade_id=unidade_ctx_id,
            meta_id=getattr(meta, "id", None),
            raw_value=request.POST.get("remarcado_de_id"),
            ignore_item_id=pi.id,
        )
        if remarcado_de_selected_id is None:
            remarcado_de_selected_id = remarcado_de_current_id

        if status_execucao in {NAO_REALIZADA, NAO_REALIZADA_JUSTIFICADA} and not obs_final:
            form_errors["observacoes"] = "Informe uma observacao para salvar este status."
        if status_execucao == REMARCADA_CONCLUIDA and not remarcado_de_selected_id:
            form_errors["remarcado_de_id"] = "Selecione de qual atividade nao realizada esta conclusao foi remarcada."

        if form_errors:
            if form_errors.get("observacoes"):
                messages.error(request, form_errors["observacoes"])
            elif form_errors.get("remarcado_de_id"):
                messages.error(request, form_errors["remarcado_de_id"])
            contexto = {
                "item": pi,
                "programacao": programacao,
                "meta": meta,
                "atividade": getattr(meta, "atividade", None),
                "veiculo": getattr(pi, "veiculo", None),
                "servidores": servidores,
                "item_remarcado": bool(getattr(pi, "remarcado_de_id", None)),
                "permite_status_remarcado": permite_status_remarcado,
                "remarcacao_opcoes": remarcacao_opcoes,
                "remarcado_de_selected_id": remarcado_de_selected_id,
                "next": safe_next_url(request, "/minhas-metas/"),
                "pendentes_total": pendentes_total,
                "pendentes_preview": pendentes_preview,
                "pendentes_tem_mais": pendentes_tem_mais,
                "pendentes_confirmacao_obrigatoria": False,
                "confirmar_pendentes_checked": confirmar_pendentes,
                "status_execucao_current": status_execucao,
                "source": source_context,
                "form_errors": form_errors,
            }
            return render(request, "minhas_metas/concluir_item.html", contexto)

        if (not ignorar_pendentes) and concluido_flag and pendentes_total > 0 and not confirmar_pendentes:
            # exige confirmacao explícita antes de concluir com pendencias
            contexto = {
                "item": pi,
                "programacao": programacao,
                "meta": meta,
                "atividade": getattr(meta, "atividade", None),
                "veiculo": getattr(pi, "veiculo", None),
                "servidores": servidores,
                "item_remarcado": bool(getattr(pi, "remarcado_de_id", None)),
                "permite_status_remarcado": permite_status_remarcado,
                "remarcacao_opcoes": remarcacao_opcoes,
                "remarcado_de_selected_id": remarcado_de_selected_id,
                "next": safe_next_url(request, "/minhas-metas/"),
                "pendentes_total": pendentes_total,
                "pendentes_preview": pendentes_preview,
                "pendentes_tem_mais": pendentes_tem_mais,
                "pendentes_confirmacao_obrigatoria": True,
                "confirmar_pendentes_checked": confirmar_pendentes,
                "status_execucao_current": status_execucao,
                "source": source_context,
                "form_errors": form_errors,
            }
            return render(request, "minhas_metas/concluir_item.html", contexto)

        before_snapshot = snapshot_programacao_dia(unidade_ctx_id, prog.data)

        with transaction.atomic():
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

            if marcado_com_status:
                concluido_em = timezone.now()
                concluido_por_id = getattr(request.user, "id", None)
            else:
                concluido_em = None
                concluido_por_id = None
            nao_realizada_justificada = status_execucao == NAO_REALIZADA_JUSTIFICADA
            remarcado_de_update_id = remarcado_de_selected_id if status_execucao == REMARCADA_CONCLUIDA else None

            (
                ProgramacaoItem.objects
                .select_for_update()
                .filter(pk=pi.pk, programacao__unidade_id=unidade_ctx_id)
                .update(
                    concluido=concluido_flag,
                    concluido_em=concluido_em,
                    nao_realizada_justificada=nao_realizada_justificada,
                    concluido_por_id=concluido_por_id,
                    observacao=obs_final,
                    remarcado_de_id=remarcado_de_update_id,
                )
            )
            after_snapshot = snapshot_programacao_dia(unidade_ctx_id, prog.data)
            record_programacao_day_diff_after_commit(
                unidade_id=unidade_ctx_id,
                data_ref=prog.data,
                user=request.user,
                before_snapshot=before_snapshot,
                after_snapshot=after_snapshot,
                origem="status_form",
            )

        messages.success(request, "Item atualizado com sucesso.")
        back_url = safe_next_url(request, "/minhas-metas/")
        return redirect(back_url)

    contexto = {
        "item": pi,
        "programacao": programacao,
        "meta": meta,
        "atividade": getattr(meta, "atividade", None),
        "veiculo": getattr(pi, "veiculo", None),
        "servidores": servidores,
        "item_remarcado": bool(getattr(pi, "remarcado_de_id", None)),
        "permite_status_remarcado": permite_status_remarcado,
        "remarcacao_opcoes": remarcacao_opcoes,
        "remarcado_de_selected_id": remarcado_de_current_id,
        "next": safe_next_url(request, "/minhas-metas/"),
        "pendentes_total": pendentes_total,
        "pendentes_preview": pendentes_preview,
        "pendentes_tem_mais": pendentes_tem_mais,
        "pendentes_confirmacao_obrigatoria": False,
        "confirmar_pendentes_checked": False,
        "status_execucao_current": _item_execucao_status(pi),
        "source": source_context,
        "form_errors": {},
    }
    return render(request, "minhas_metas/concluir_item.html", contexto)



