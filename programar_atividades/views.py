from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Tuple, Optional

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse, Http404, HttpResponseBadRequest, HttpRequest
from django.shortcuts import render
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_POST

from core.utils import get_unidade_atual, get_unidade_atual_id
from metas.models import Meta, MetaAlocacao
from servidores.models import Servidor
from descanso.models import Descanso
from .models import Programacao, ProgramacaoItem, ProgramacaoItemServidor
from django.template.loader import render_to_string
from django.utils.dateparse import parse_date
from django.db import models
from datetime import date, timedelta
import calendar
import traceback  # adicione no topo do arquivo (se ainda não existir)
from typing import List, Dict, Tuple

# Veículo é opcional (ambientes sem o app)
try:
    from veiculos.models import Veiculo  # type: ignore
except Exception:
    Veiculo = None  # type: ignore

try:
    from plantao.models import Plantao  # type: ignore
except Exception:
    Plantao = None 

# ---------------------- PÁGINA DO CALENDÁRIO ---------------------- #
@login_required
def calendar_view(request: HttpRequest):
    """Renderiza o calendário e injeta veículos ativos para o <select> dos cards."""
    unidade = get_unidade_atual(request)
    if not unidade:
        raise Http404("Unidade atual não definida para o usuário.")

    veiculos_ativos = []
    if Veiculo is not None:
        veiculos_ativos = Veiculo.objects.filter(unidade=unidade, ativo=True).order_by("nome")

    return render(
        request,
        "programar_atividades/calendar.html",
        {"unidade": unidade, "veiculos_ativos": veiculos_ativos},
    )


# ---------------------- HELPERS NUMÉRICOS ---------------------- #
from django.db import models  # já existe no arquivo

def _plantonistas_do_intervalo(unidade_id, ini, fim):
    """
    Retorna lista única de {'nome', 'telefone'} para semanas do PLANTÃO
    que intersectam [ini, fim], respeitando unidade quando houver.
    Usa telefone_snapshot do item; fallback para campos do Servidor.
    """
    if Plantao is None or ini is None or fim is None:
        return []

    # respeita unidade se o model Plantao tiver o campo
    try:
        field_names = [f.name for f in Plantao._meta.fields]
    except Exception:
        field_names = []
    unidade_filter = {}
    if ("unidade" in field_names or "unidade_id" in field_names) and unidade_id:
        unidade_filter = {"unidade_id": unidade_id}

    plantoes = Plantao.objects.filter(inicio__lte=fim, fim__gte=ini, **unidade_filter)

    seen = set()
    out = []

    for p in plantoes:
        # tenta .semanas, senão .semana_set
        if hasattr(p, "semanas"):
            semanas_qs = p.semanas.all()
        elif hasattr(p, "semana_set"):
            semanas_qs = p.semana_set.all()
        else:
            semanas_qs = []

        for sem in semanas_qs:
            # intersecta?
            if getattr(sem, "fim", None) and getattr(sem, "inicio", None):
                if sem.fim < ini or sem.inicio > fim:
                    continue
            # itens/servidores (tenta .itens, senão .semanaservidor_set)
            if hasattr(sem, "itens"):
                itens_qs = sem.itens.all()
            elif hasattr(sem, "semanaservidor_set"):
                itens_qs = sem.semanaservidor_set.all()
            else:
                itens_qs = []

            for item in itens_qs.order_by("ordem"):
                srv = getattr(item, "servidor", None)
                nome = (getattr(srv, "nome", "") or "").strip()
                if not nome:
                    continue

                tel_snapshot = getattr(item, "telefone_snapshot", "") or ""
                tel = (
                    tel_snapshot
                    or getattr(srv, "telefone", None)
                    or getattr(srv, "telefone_celular", None)
                    or getattr(srv, "celular", None)
                    or getattr(srv, "fone", None)
                    or ""
                )
                key = nome.lower()
                if key not in seen:
                    seen.add(key)
                    out.append({"nome": nome, "telefone": tel})
    return out


def _num_or_none(v: Any) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, (int, float, Decimal)):
        try:
            return int(v)
        except Exception:
            return None
    try:
        return int(v)
    except Exception:
        try:
            return int(float(v))
        except Exception:
            return None


def _find_numeric_attr(obj: Any, include_substr, exclude_substr=()) -> Tuple[Optional[str], Optional[int]]:
    inc = tuple(s.lower() for s in include_substr)
    exc = tuple(s.lower() for s in exclude_substr)

    favoritos = [
        "qtd_alocada", "quantidade_alocada", "alocado", "quantidade",
        "alocado_unidade", "valor_alocado", "alocada",
        "executado", "qtd_executado", "quantidade_executada", "realizado", "feito",
        "progresso", "quantidade_total", "qtd_total", "alvo", "meta",
    ]
    for name in favoritos:
        if hasattr(obj, name):
            v = getattr(obj, name)
            if not callable(v):
                nv = _num_or_none(v)
                if nv is not None:
                    low = name.lower()
                    if any(t in low for t in inc) and not any(t in low for t in exc):
                        return name, nv

    for name in dir(obj):
        if name.startswith("_"):
            continue
        if any(t in name.lower() for t in exc):
            continue
        if not any(t in name.lower() for t in inc):
            continue
        try:
            v = getattr(obj, name)
        except Exception:
            continue
        if callable(v):
            continue
        nv = _num_or_none(v)
        if nv is not None:
            return name, nv

    return None, None


# ---------------------- METAS DISPONÍVEIS ---------------------- #
@login_required
@require_GET
def metas_disponiveis(request: HttpRequest):
    """
    Metas da UNIDADE atual (opcional: ?atividade=<id>) com:
      - nome, atividade_nome, data_limite
      - alocado_unidade, executado_unidade (somados por meta)
      - meta_total (alvo total da meta)
    """
    unidade = get_unidade_atual(request)
    atividade_id = request.GET.get("atividade")
    metas = []

    if not unidade:
        return JsonResponse({"metas": metas})

    qs = (
        MetaAlocacao.objects.select_related("meta", "meta__atividade")
        .filter(unidade=unidade)
    )
    if atividade_id:
        qs = qs.filter(meta__atividade_id=atividade_id)

    bucket = {}
    for al in qs:
        meta = getattr(al, "meta", None)
        if not meta or not getattr(meta, "id", None):
            continue
        mid = meta.id

        # valores por alocação
        _, alocado_val = _find_numeric_attr(
            al, include_substr=("aloc", "qtd", "quant"), exclude_substr=("exec", "realiz", "feito")
        )
        _, executado_val = _find_numeric_attr(
            al, include_substr=("exec", "realiz", "feito")
        )

        if mid not in bucket:
            atividade = getattr(meta, "atividade", None)
            _, meta_total_val = _find_numeric_attr(
                meta, include_substr=("total", "alvo", "quant", "qtd", "meta"),
                exclude_substr=("exec", "realiz", "feito"),
            )

            data_limite = None
            for cand in ("data_limite", "deadline", "prazo", "limite"):
                if hasattr(meta, cand):
                    data_limite = getattr(meta, cand)
                    break

            bucket[mid] = {
                "id": mid,
                "nome": getattr(meta, "titulo", None) or getattr(meta, "nome", None) or str(meta),
                "atividade_id": getattr(atividade, "id", None),
                "atividade_nome": (
                    getattr(atividade, "nome", None) or getattr(atividade, "titulo", None) or (str(atividade) if atividade else None)
                ),
                "data_limite": data_limite.isoformat() if hasattr(data_limite, "isoformat") else data_limite,
                "alocado_unidade": 0,
                "executado_unidade": 0,
                "meta_total": meta_total_val or 0,
            }

        if alocado_val:
            bucket[mid]["alocado_unidade"] += alocado_val
        if executado_val:
            bucket[mid]["executado_unidade"] += executado_val

    metas = list(bucket.values())
    metas.sort(key=lambda x: x["nome"].lower())
    return JsonResponse({"metas": metas})


# ---------------------- SERVIDORES POR DATA ---------------------- #
@login_required
@require_GET
def servidores_para_data(request: HttpRequest):
    """
    Retorna:
      - 'livres': servidores disponíveis no dia
      - 'impedidos': servidores em descanso/impedimento (com motivo)
    """
    data_str = request.GET.get("data")
    if not data_str:
        return JsonResponse({"erro": "Data não informada"}, status=400)
    try:
        dia = datetime.strptime(data_str, "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse({"erro": "Formato inválido da data"}, status=400)

    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        return JsonResponse({"erro": "Unidade não definida"}, status=400)

    todos = Servidor.objects.filter(unidade_id=unidade_id, ativo=True).order_by("nome")

    descansos_qs = (
        Descanso.objects.filter(
            servidor__unidade_id=unidade_id,
            data_inicio__lte=dia,
            data_fim__gte=dia,
        )
        .select_related("servidor")
    )

    motivo_map = {}
    for d in descansos_qs:
        motivo_map[d.servidor_id] = getattr(
            d, "get_tipo_display", lambda: getattr(d, "tipo", "Descanso")
        )()

    impedidos_ids = set(motivo_map.keys())
    livres_qs = todos.exclude(id__in=impedidos_ids)
    impedidos_qs = todos.filter(id__in=impedidos_ids)

    def map_servidor(s, motivo=None):
        return {"id": s.id, "nome": s.nome, "motivo": motivo or "Descanso"}

    return JsonResponse(
        {
            "livres": [map_servidor(s) for s in livres_qs],
            "impedidos": [map_servidor(s, motivo_map.get(s.id)) for s in impedidos_qs],
        }
    )

# ---------------------- SALVAR PROGRAMAÇÃO ---------------------- #
def _to_pk(v):
    """Converte para PK int > 0. '', 'null', None ou inválidos => None."""
    if v in (None, "", "null", "undefined"):
        return None
    try:
        iv = int(v)
        return iv if iv > 0 else None
    except (TypeError, ValueError):
        return None

# Detecta o tipo da PK do Veiculo para coerção correta
def _coerce_veiculo_pk(raw):
    if raw in (None, "", "null", "undefined"):
        return None
    if Veiculo is None:
        return None
    # UUID? então preserve string
    if isinstance(Veiculo._meta.pk, models.UUIDField):
        return str(raw).strip()
    # Inteiro? tente converter com segurança
    try:
        iv = int(str(raw).strip())
        return iv if iv > 0 else None
    except (TypeError, ValueError):
        return None

@login_required
@require_POST
def salvar_programacao(request):
    """
    Snapshot do dia: recria os itens exatamente como o front enviou.
    - Se itens == []: limpa o dia (sem erro).
    - Não cria ProgramacaoItem sem servidores.
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "JSON inválido."}, status=400)

    data_str = (payload or {}).get("data")
    itens = (payload or {}).get("itens") or []

    try:
        dia = date.fromisoformat(data_str)
    except Exception:
        return JsonResponse({"ok": False, "error": "Data inválida."}, status=400)

    if not isinstance(itens, list):
        return JsonResponse({"ok": False, "error": "'itens' deve ser lista."}, status=400)

    unidade = get_unidade_atual(request)
    if not unidade:
        return JsonResponse({"ok": False, "error": "Unidade do usuário não localizada."}, status=400)

    with transaction.atomic():
        prog, _ = Programacao.objects.select_for_update().get_or_create(
            unidade=unidade, data=dia, defaults={"criado_por": request.user}
        )

        # limpa tudo do dia
        ProgramacaoItemServidor.objects.filter(item__programacao=prog).delete()
        ProgramacaoItem.objects.filter(programacao=prog).delete()

        if len(itens) == 0:
            # opcional: remover a própria programação quando fica vazia
            prog.delete()
            return JsonResponse({
                "ok": True,
                "programacao_id": None,
                "itens": 0,
                "servidores_vinculados": 0,
                "itens_com_veiculo": 0,
            })

        created_items = 0
        servidores_vinculados = 0

        for it in itens:
            meta_id = str(it.get("meta_id") or "").strip()
            if not meta_id:
                continue
            try:
                meta = Meta.objects.get(pk=meta_id)
            except Meta.DoesNotExist:
                continue

            # servidores (únicos, inteiros)
            servidores_ids_raw = list(dict.fromkeys(it.get("servidores") or []))
            servidores_ids = []
            for sid in servidores_ids_raw:
                sid_int = _to_pk(sid)
                if sid_int:
                    servidores_ids.append(sid_int)

            if not servidores_ids:
                # não cria item sem servidores
                continue

            # --- veículo: aceita int/UUID, normaliza e verifica existência ---
            veiculo_pk = _coerce_veiculo_pk(it.get("veiculo_id"))
            veiculo_kw = {}
            if veiculo_pk is not None and Veiculo is not None:
                if Veiculo.objects.filter(pk=veiculo_pk, unidade=unidade).exists():
                    veiculo_kw = {"veiculo_id": veiculo_pk}
                else:
                    # se quiser, pode ignorar unidade na checagem:
                    # if Veiculo.objects.filter(pk=veiculo_pk).exists(): ...
                    pass

            item = ProgramacaoItem.objects.create(
                programacao=prog,
                meta=meta,
                **veiculo_kw,
            )
            created_items += 1

            s_ok = list(
                Servidor.objects.filter(pk__in=servidores_ids, unidade=unidade)
                .values_list("pk", flat=True)
            )
            ProgramacaoItemServidor.objects.bulk_create(
                [ProgramacaoItemServidor(item=item, servidor_id=sid) for sid in s_ok],
                ignore_conflicts=True,
            )
            servidores_vinculados += len(s_ok)

        if created_items == 0:
            prog.delete()
            return JsonResponse({
                "ok": True,
                "programacao_id": None,
                "itens": 0,
                "servidores_vinculados": 0,
                "itens_com_veiculo": 0,
            })

        # Métrica extra p/ conferência
        itens_com_veiculo = ProgramacaoItem.objects.filter(
            programacao=prog
        ).exclude(veiculo_id__isnull=True).count()

    return JsonResponse({
        "ok": True,
        "programacao_id": prog.id,
        "itens": created_items,
        "servidores_vinculados": servidores_vinculados,
        "itens_com_veiculo": itens_com_veiculo,
    })

# ---------------------- ATUALIZAÇÕES ---------------------- #
@login_required
@require_POST
def atualizar_programacao(request: HttpRequest):
    """JSON: {"programacao_id": 1, "observacao": "txt", "concluida": true|false}"""
    try:
        data = json.loads(request.body or "{}")
    except Exception:
        return HttpResponseBadRequest("JSON inválido")

    pid = data.get("programacao_id")
    if not pid:
        return HttpResponseBadRequest("programacao_id obrigatório")

    try:
        prog = Programacao.objects.get(pk=pid, unidade_id=get_unidade_atual_id(request))
    except Programacao.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Programação não encontrada"}, status=404)

    fields = []
    if "observacao" in data:
        prog.observacao = str(data.get("observacao") or "")
        fields.append("observacao")
    if "concluida" in data:
        prog.marcar_concluida(request.user, bool(data.get("concluida")))
        fields += ["concluida", "concluida_em", "concluida_por"]

    if fields:
        prog.save(update_fields=fields)
    return JsonResponse({"ok": True})


@login_required
@require_POST
def atualizar_item(request: HttpRequest):
    """JSON: {"item_id": 123, "observacao": "txt", "concluido": true|false}"""
    try:
        data = json.loads(request.body or "{}")
    except Exception:
        return HttpResponseBadRequest("JSON inválido")

    iid = data.get("item_id")
    if not iid:
        return HttpResponseBadRequest("item_id obrigatório")

    try:
        item = ProgramacaoItem.objects.select_related("programacao").get(
            pk=iid, programacao__unidade_id=get_unidade_atual_id(request)
        )
    except ProgramacaoItem.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Item não encontrado"}, status=404)

    fields = []
    if "observacao" in data:
        item.observacao = str(data.get("observacao") or "")
        fields.append("observacao")
    if "concluido" in data:
        item.marcar_concluido(request.user, bool(data.get("concluido")))
        fields += ["concluido", "concluido_em", "concluido_por"]

    if fields:
        item.save(update_fields=fields)
    return JsonResponse({"ok": True})


# ---------------------- FEED DO FULLCALENDAR ---------------------- #
@login_required
@require_GET
def events_feed(request: HttpRequest):
    """Retorna programações como eventos all-day do FullCalendar."""
    start = request.GET.get("start")
    end = request.GET.get("end")
    start_date = parse_date(start[:10]) if start else None
    end_date = parse_date(end[:10]) if end else None

    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        return JsonResponse([], safe=False)

    qs = Programacao.objects.filter(unidade_id=unidade_id)
    if start_date and end_date:
        qs = qs.filter(data__gte=start_date, data__lte=end_date)

    data = []
    for prog in qs.select_related("unidade"):
        qtd_itens = prog.itens.count()
        title = f"({qtd_itens} atividade{'s' if qtd_itens != 1 else ''})"
        if getattr(prog, "concluida", False):
            title = "✅ " + title
        data.append(
            {"id": prog.id, "title": title, "start": prog.data.isoformat(), "allDay": True}
        )
    return JsonResponse(data, safe=False)

@login_required
@require_GET
def programacao_do_dia(request: HttpRequest):
    data_str = request.GET.get("data")
    if not data_str:
        return JsonResponse({"ok": False, "error": "Data não informada"}, status=400)
    try:
        dia = date.fromisoformat(data_str)
    except Exception:
        return JsonResponse({"ok": False, "error": "Data inválida"}, status=400)

    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        return JsonResponse({"ok": False, "error": "Unidade não definida"}, status=400)

    try:
        prog = (
            Programacao.objects
            .select_related("unidade")
            .prefetch_related(
                models.Prefetch(
                    "itens",
                    queryset=ProgramacaoItem.objects
                        .select_related("meta", "veiculo")
                        .prefetch_related(
                            models.Prefetch(
                                "servidores",
                                queryset=ProgramacaoItemServidor.objects.select_related("servidor")
                            )
                        )
                )
            )
            .get(unidade_id=unidade_id, data=dia)
        )
    except Programacao.DoesNotExist:
        return JsonResponse({"ok": True, "programacao": None})

    itens = []
    for it in prog.itens.all():
        veiculo_id = getattr(it, "veiculo_id", None)

        veiculo_label = None
        if getattr(it, "veiculo", None):
            nome  = getattr(it.veiculo, "nome", "") or "Veículo"
            placa = getattr(it.veiculo, "placa", "") or ""
            veiculo_label = f"{nome} - {placa}".strip(" -")
        elif veiculo_id:
            veiculo_label = f"Veículo #{veiculo_id} (indisponível)"

        itens.append({
            "id": it.id,
            "meta_id": it.meta_id,
            "meta_nome": getattr(it.meta, "titulo", None) or getattr(it.meta, "nome", None) or str(it.meta),
            "veiculo_id": veiculo_id,
            "veiculo_label": veiculo_label,
            "servidores": [{"id": pis.servidor_id, "nome": pis.servidor.nome} for pis in it.servidores.all()],
            "observacao": it.observacao,
            "concluido": it.concluido,
        })

    return JsonResponse({"ok": True, "programacao": {
        "id": prog.id,
        "data": prog.data.isoformat(),
        "observacao": prog.observacao,
        "concluida": prog.concluida,
        "itens": itens,
    }})

login_required
@require_POST
def excluir_programacao(request: HttpRequest):
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
        data_str = data.get("data")
        if not data_str:
            return JsonResponse({"ok": False, "error": "Informe programacao_id ou data."}, status=400)
        try:
            dia = date.fromisoformat(data_str)
        except Exception:
            return JsonResponse({"ok": False, "error": "Data inválida."}, status=400)
        prog = Programacao.objects.filter(unidade_id=unidade_id, data=dia).first()
        if not prog:
            return JsonResponse({"ok": True, "deleted": False})  # nada para excluir

    # cascata: itens/servidores serão removidos pelas FKs
    prog.delete()
    return JsonResponse({"ok": True, "deleted": True})


# programar_atividades/views.py (adicione ao seu arquivo)

# --- helpers para semanas Sáb → Sex (compatível com Plantao) ---
def _prev_or_same_saturday(d: date) -> date:
    """Retorna o sábado anterior ou o próprio se d for sábado.
    weekday(): Mon=0 .. Sun=6 ; Saturday=5"""
    return d - timedelta(days=(d.weekday() - 5) % 7)

def _next_or_same_friday(d: date) -> date:
    """Retorna a próxima sexta (ou a própria se d for sexta). Friday=4"""
    return d + timedelta(days=(4 - d.weekday()) % 7)

def _weeks_sat_to_fri(dt_ini: date, dt_fim: date):
    """
    Gera uma lista de (inicio, fim) onde cada semana começa no sábado e termina na sexta.
    O primeiro início é o sábado <= dt_ini; o último fim é a sexta >= dt_fim.
    Retorna lista de tuples (inicio: date, fim: date).
    """
    start = _prev_or_same_saturday(dt_ini)
    last = _next_or_same_friday(dt_fim)
    weeks = []
    cur = start
    while cur <= last:
        weeks.append((cur, cur + timedelta(days=6)))  # sábado -> sexta (6 dias depois)
        cur += timedelta(days=7)
    return weeks

def _ordinal_pt(n: int) -> str:
    ord_map = {1: "Primeira", 2: "Segunda", 3: "Terceira", 4: "Quarta", 5: "Quinta", 6: "Sexta", 7: "Sétima"}
    return ord_map.get(n, f"{n}ª")

@login_required
@require_GET
def relatorios_parcial(request: HttpRequest):
    """
    Partial de 'Relatório semanal' (Sáb→Sex) sem o bloco agregado de plantonistas.
    """
    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        return JsonResponse({"ok": False, "html": "<div class='alert alert-warning'>Unidade não definida.</div>"})

    # --- intervalo base ---
    today = date.today()
    start_qs = parse_date(request.GET.get("start") or "") or today.replace(day=1)

    # >>> fallback do fim do mês com base em start_qs (e não em today)
    if start_qs.month == 12:
        month_end = date(start_qs.year, 12, 31)
    else:
        next_month = date(start_qs.year, start_qs.month + 1, 1)
        month_end = next_month - timedelta(days=1)

    end_qs = parse_date(request.GET.get("end") or "") or month_end

    # --- semanas Sáb->Sex ---
    raw_weeks = _weeks_sat_to_fri(start_qs, end_qs)
    semanas = []
    for i, (ini, fim) in enumerate(raw_weeks, start=1):
        label = f"{_ordinal_pt(i)} ({ini.strftime('%d/%m/%Y')} → {fim.strftime('%d/%m/%Y')})"
        semanas.append({"index": i, "inicio": ini, "fim": fim, "label": label})

    # --- escolhe a semana que contém start_qs (fallback: primeira) ---
    selected_week = None
    for wk in semanas:
        if wk["inicio"] <= start_qs <= wk["fim"]:
            selected_week = wk
            break
    if not selected_week and semanas:
        selected_week = semanas[0]

    # --- monta a semana detalhada (por dia) ---
    semana_detalhada = []
    if selected_week:
        ini = selected_week["inicio"]
        fim = selected_week["fim"]
        dias_da_semana = [ini + timedelta(days=i) for i in range(7)]

        programacoes = (
            Programacao.objects
            .filter(unidade_id=unidade_id, data__range=(ini, fim))
            .prefetch_related(
                models.Prefetch(
                    "itens",
                    queryset=ProgramacaoItem.objects
                        .select_related("meta", "veiculo")
                        .prefetch_related("servidores__servidor")
                )
            )
        )
        prog_map = {p.data: p for p in programacoes}

        for dia in dias_da_semana:
            prog = prog_map.get(dia)
            atividades = []
            if prog:
                for item in prog.itens.all():
                    # servidores do item (com tentativa de telefone)
                    servidores = []
                    for ps in item.servidores.all():
                        srv = getattr(ps, "servidor", None)
                        if srv:
                            tel = (
                                getattr(srv, "telefone", None)
                                or getattr(srv, "telefone_celular", None)
                                or getattr(srv, "celular", None)
                                or getattr(srv, "fone", None)
                                or None
                            )
                            servidores.append({
                                "id": getattr(srv, "id", None),
                                "nome": getattr(srv, "nome", str(srv)),
                                "telefone": tel
                            })
                        else:
                            servidores.append({"id": None, "nome": str(ps), "telefone": None})

                    veiculo_label = None
                    if getattr(item, "veiculo", None):
                        nome_v  = getattr(item.veiculo, "nome", "") or "Veículo"
                        placa_v = getattr(item.veiculo, "placa", "") or ""
                        veiculo_label = f"{nome_v} - {placa_v}".strip(" -")

                    atividades.append({
                        "titulo": getattr(item.meta, "nome", getattr(item.meta, "titulo", str(item.meta))),
                        "servidores": servidores,
                        "veiculo": veiculo_label
                    })

            semana_detalhada.append({
                "data": dia,
                "nome_semana": nome_dia_semana(dia),
                # mantemos sem 'plantonista' agregado aqui; se precisar por-dia, você já tem 'atividades/servidores'
                "atividades": atividades,
                "is_weekend": dia.weekday() in (5, 6),
            })

    # >>> BLOCO REMOVIDO: não agregamos mais plantonistas_semana no parcial
    plantonistas_semana = []  # mantém compatibilidade com template usando um IF

    try:
        html = render_to_string(
            "programar_atividades/_relatorios.html",
            {
                "start": start_qs,
                "end": end_qs,
                "semanas": semanas,
                "semana": semana_detalhada,
                "plantonistas_semana": plantonistas_semana,  # vazio => não renderiza se houver {% if %}
                "selected_week": selected_week,
            },
            request=request,
        )
    except Exception:
        tb_str = traceback.format_exc()
        print("ERRO ao renderizar _relatorios.html:\n", tb_str)
        return JsonResponse({
            "ok": False,
            "html": (
                "<div class='alert alert-danger'>"
                "<strong>Erro ao renderizar relatório (ver console/server logs)</strong><br>"
                f"<pre style='white-space:pre-wrap; font-size:12px'>{tb_str}</pre>"
                "</div>"
            )
        })

    return JsonResponse({"ok": True, "html": html})

def nome_dia_semana(data: date) -> str:
    dias = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira", "Sábado", "Domingo"]
    return dias[data.weekday()] if 0 <= data.weekday() < 7 else data.strftime("%A")



# assume get_unidade_atual_id e _weeks_sat_to_fri, _ordinal_pt, nome_dia_semana já definidos no mesmo módulo


@login_required
def imprimir_programacao(request):
    """
    Página de impressão: mostra grupos semanais (Sáb→Sex) com servidores e telefones.
    Query params (opcional): ?start=YYYY-MM-DD&end=YYYY-MM-DD
    Fallback: se não vier, usa mês do parâmetro start (ou mês atual).
    """
    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        # mostra template vazio / mensagem amigável
        return render(request, "programar_atividades/print_programacao.html", {
            "plantao": {"inicio": None, "fim": None},
            "grupos": [],
            "now": datetime.now(),
            "request": request,
        })

    # parse dos parâmetros: start (fallback para 1º do mês atual), end (fallback fim do mês de start)
    today = date.today()
    start_qs = parse_date(request.GET.get("start") or "") or today.replace(day=1)

    if start_qs.month == 12:
        month_end = date(start_qs.year, 12, 31)
    else:
        next_month = date(start_qs.year, start_qs.month + 1, 1)
        month_end = next_month - timedelta(days=1)

    end_qs = parse_date(request.GET.get("end") or "") or month_end

    # calcula semanas sáb→sex
    raw_weeks = _weeks_sat_to_fri(start_qs, end_qs)

    # Carrega todas as programações do intervalo (uma única query) com itens e servidores para prefetch
    programacoes_qs = (
        Programacao.objects
        .filter(unidade_id=unidade_id, data__range=(start_qs, end_qs))
        .prefetch_related(
            models.Prefetch(
                "itens",
                queryset=ProgramacaoItem.objects
                    .select_related("meta", "veiculo")
                    .prefetch_related(
                        models.Prefetch(
                            "servidores",
                            queryset=ProgramacaoItemServidor.objects.select_related("servidor")
                        )
                    )
            )
        )
    )

    # índice por data para acesso rápido
    prog_map = {}
    for p in programacoes_qs:
        prog_map.setdefault(p.data, []).append(p)

    grupos: List[Dict] = []
    for ini, fim in raw_weeks:
        # junta programacoes no período [ini,fim]
        servidores_ids = set()
        # percorre programacoes daquele período usando prog_map
        d = ini
        while d <= fim:
            for p in prog_map.get(d, []):
                for item in p.itens.all():
                    for pis in item.servidores.all():
                        sid = getattr(pis, "servidor_id", None)
                        if sid:
                            servidores_ids.add(sid)
            d = d + timedelta(days=1)

        servidores = []
        if servidores_ids:
            qs = Servidor.objects.filter(id__in=servidores_ids, unidade_id=unidade_id).order_by("nome")
            for s in qs:
                telefone = (
                    getattr(s, "telefone", None)
                    or getattr(s, "telefone_celular", None)
                    or getattr(s, "celular", None)
                    or getattr(s, "fone", None)
                    or ""
                )
                servidores.append({"id": s.id, "nome": s.nome, "telefone": telefone})

        grupos.append({"periodo": (ini, fim), "servidores": servidores})

    plantao = {"inicio": raw_weeks[0][0] if raw_weeks else start_qs,
               "fim": raw_weeks[-1][1] if raw_weeks else end_qs}

    return render(request, "programar_atividades/print_programacao.html", {
        "plantao": plantao,
        "grupos": grupos,
        "now": datetime.now(),
        "request": request,
    })

@login_required
def print_programacao(request):
    """
    Gera uma versão para impressão da programação entre ?start=YYYY-MM-DD&end=YYYY-MM-DD.
    Agrupa por dia (cada Programacao => um grupo com lista de servidores únicos).
    """
    start_str = request.GET.get("start")
    end_str = request.GET.get("end")
    if not start_str or not end_str:
        return HttpResponseBadRequest("Parâmetros 'start' e 'end' são obrigatórios (YYYY-MM-DD).")

    try:
        inicio = date.fromisoformat(start_str)
        fim = date.fromisoformat(end_str)
    except Exception:
        return HttpResponseBadRequest("Formato inválido para 'start' ou 'end'. Use YYYY-MM-DD.")

    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        return HttpResponseBadRequest("Unidade do usuário não definida.")

    # Carrega programações do intervalo com itens/servidores/veículos/meta
    programacoes = (
        Programacao.objects
        .filter(unidade_id=unidade_id, data__gte=inicio, data__lte=fim)
        .select_related()  # ajuste se quiser
        .prefetch_related(
            models.Prefetch(
                "itens",
                queryset=ProgramacaoItem.objects
                    .select_related("meta", "veiculo")
                    .prefetch_related("servidores__servidor")
            )
        )
        .order_by("data")
    )

    grupos = []
    for prog in programacoes:
        servidores_map: dict = {}  # nome -> telefone (mantém únicos)
        # percorre itens do dia e coleta servidores
        for item in prog.itens.all():
            for pis in item.servidores.all():
                srv = getattr(pis, "servidor", None)
                if not srv:
                    continue
                nome = getattr(srv, "nome", str(srv)).strip()
                # tenta vários campos comuns para telefone
                tel = (
                    getattr(srv, "telefone", None)
                    or getattr(srv, "telefone_celular", None)
                    or getattr(srv, "celular", None)
                    or getattr(srv, "fone", None)
                    or None
                )
                tel = tel.strip() if isinstance(tel, str) else tel
                if nome and nome not in servidores_map:
                    servidores_map[nome] = tel

        servidores = [{"nome": n, "telefone": servidores_map[n]} for n in sorted(servidores_map.keys())]

        grupos.append({
            "periodo": (prog.data, prog.data),  # template espera tupla (inicio, fim)
            "servidores": servidores,
        })

    plantao = {"inicio": inicio, "fim": fim}

    context = {
        "plantao": plantao,
        "grupos": grupos,
        "now": datetime.now(),
        "request": request,
    }

    return render(request, "programar_atividades/print_programacao.html", context)



@login_required
@require_GET
def print_relatorio_semana(request):
    """
    Página de impressão do RELATÓRIO SEMANAL (tabela).
    Usa a semana Sáb→Sex que contém 'start'. Os plantonistas vêm do app Plantão.
    Fallback por palavras-chave só é usado se não houver dados no Plantão.
    """
    start_str = request.GET.get("start")
    end_str   = request.GET.get("end")
    if not start_str or not end_str:
        return HttpResponseBadRequest("Parâmetros 'start' e 'end' são obrigatórios (YYYY-MM-DD).")

    try:
        start = date.fromisoformat(start_str)
        end   = date.fromisoformat(end_str)
    except Exception:
        return HttpResponseBadRequest("Formato inválido para 'start' ou 'end'. Use YYYY-MM-DD.")

    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        return HttpResponseBadRequest("Unidade do usuário não definida.")

    # --------- determina a semana Sáb→Sex que contém 'start' ---------
    weeks = _weeks_sat_to_fri(start, end)
    if not weeks:
        weeks = [(start, end)]
    sel_ini, sel_fim = None, None
    for ini, fim in weeks:
        if ini <= start <= fim:
            sel_ini, sel_fim = ini, fim
            break
    if sel_ini is None:
        sel_ini, sel_fim = weeks[0]

    # --------- carrega programações do range com itens/servidores/veículo ---------
    programacoes = (
        Programacao.objects
        .filter(unidade_id=unidade_id, data__range=(sel_ini, sel_fim))
        .prefetch_related(
            models.Prefetch(
                "itens",
                queryset=ProgramacaoItem.objects
                    .select_related("meta", "veiculo")
                    .prefetch_related("servidores__servidor")
            )
        )
    )
    prog_map = {p.data: p for p in programacoes}

    # --------- monta estrutura da semana (7 dias) ---------
    dias = [sel_ini + timedelta(days=i) for i in range(7)]
    semana = []
    for dia in dias:
        prog = prog_map.get(dia)
        atividades = []
        if prog:
            for item in prog.itens.all():
                # servidores do item
                servidores = []
                for ps in item.servidores.all():
                    srv = getattr(ps, "servidor", None)
                    if not srv:
                        continue
                    tel = (
                        getattr(srv, "telefone", None)
                        or getattr(srv, "telefone_celular", None)
                        or getattr(srv, "celular", None)
                        or getattr(srv, "fone", None)
                        or None
                    )
                    servidores.append({
                        "id": getattr(srv, "id", None),
                        "nome": getattr(srv, "nome", str(srv)),
                        "telefone": tel,
                    })

                # veículo (rótulo amigável)
                veiculo_label = None
                if getattr(item, "veiculo", None):
                    nome_v  = getattr(item.veiculo, "nome", "") or "Veículo"
                    placa_v = getattr(item.veiculo, "placa", "") or ""
                    veiculo_label = f"{nome_v} - {placa_v}".strip(" -")

                atividades.append({
                    "titulo": getattr(item.meta, "nome", getattr(item.meta, "titulo", str(item.meta))),
                    "servidores": servidores,
                    "veiculo": veiculo_label or "Nenhum - veículo",
                })

        semana.append({
            "data": dia,
            "nome_semana": nome_dia_semana(dia),
            "atividades": atividades,
            "is_weekend": dia.weekday() in (5, 6),
        })

    # --------- PLANTONISTAS: oficial do app Plantão ---------
    plantonistas_semana = _plantonistas_do_intervalo(unidade_id, sel_ini, sel_fim)

    # Fallback por palavras-chave (se vazio)
    if not plantonistas_semana:
        KEYWORDS = ("vacina", "agrotóxico", "agrotoxico", "biológico", "biologico", "plantão", "plantao")
        seen = set()
        for d in semana:
            for a in d.get("atividades", []):
                t = (a.get("titulo") or "").lower()
                if any(k in t for k in KEYWORDS):
                    for s in a.get("servidores", []):
                        k = (s["nome"] or "").strip().lower()
                        if k and k not in seen:
                            seen.add(k)
                            plantonistas_semana.append({"nome": s["nome"], "telefone": s.get("telefone")})
                    break  # só a primeira atividade “especial” do dia

    context = {
        "periodo": (sel_ini, sel_fim),
        "semana": semana,
        "plantonistas_semana": plantonistas_semana,
        "now": datetime.now(),
        "request": request,
    }

    # suporta renderização inline dentro da página
    tpl = "programar_atividades/print_relatorio_semana.html"
    if request.GET.get("inline") in ("1", "true", "yes", "on"):
        tpl = "programar_atividades/_print_relatorio_semana_fragment.html"
    return render(request, tpl, context)
