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
# Veículo é opcional (ambientes sem o app)
try:
    from veiculos.models import Veiculo  # type: ignore
except Exception:
    Veiculo = None  # type: ignore


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


def _ordinal_pt(n: int) -> str:
    # retorna "Primeira", "Segunda", "3ª", ...
    ord_map = {1: "Primeira", 2: "Segunda", 3: "Terceira", 4: "Quarta", 5: "Quinta", 6: "Sexta"}
    if n in ord_map:
        return ord_map[n]
    return f"{n}ª"

def _weeks_start_to_end(start: date, end: date):
    """
    Divide o intervalo [start, end] em blocos de 7 dias:
    [start, start+6], [start+7, start+13], ...
    Retorna lista de dicts: {'index': i, 'inicio': date, 'fim': date, 'label': str}
    """
    weeks = []
    cur = start
    i = 1
    while cur <= end:
        wk_end = cur + timedelta(days=6)
        if wk_end > end:
            wk_end = end
        label = f"{_ordinal_pt(i)} ({cur.strftime('%d/%m/%Y')} → {wk_end.strftime('%d/%m/%Y')})"
        weeks.append({"index": i, "inicio": cur, "fim": wk_end, "label": label})
        cur = cur + timedelta(days=7)
        i += 1
    return weeks

@login_required
@require_GET
def relatorios_parcial(request: HttpRequest):
    """
    Retorna partial com título/intervalo e selectbox de semanas dentro do intervalo.
    Query params:
      - start=YYYY-MM-DD
      - end=YYYY-MM-DD
    """
    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        return JsonResponse({"ok": False, "html": "<div class='alert alert-warning'>Unidade não definida.</div>"})

    today = date.today()
    start_qs = parse_date(request.GET.get("start") or "") or today.replace(day=1)

    # calcula último dia do mês corrente (fallback)
    if today.month == 12:
        month_end = date(today.year, 12, 31)
    else:
        next_month = date(today.year, today.month + 1, 1)
        month_end = next_month - timedelta(days=1)

    end_qs = parse_date(request.GET.get("end") or "") or month_end

    # monta as semanas (lista de dicts com index, inicio, fim, label)
    semanas = _weeks_start_to_end(start_qs, end_qs)

    html = render_to_string(
        "programar_atividades/_relatorios.html",
        {"start": start_qs, "end": end_qs, "semanas": semanas},
        request=request,
    )
    return JsonResponse({"ok": True, "html": html})