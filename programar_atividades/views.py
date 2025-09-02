# programar_atividades/views.py
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, Http404
from django.shortcuts import render
from django.views.decorators.http import require_GET

from core.utils import get_unidade_atual, get_unidade_atual_id
from metas.models import MetaAlocacao
from servidores.models import Servidor
from descanso.models import Descanso
from veiculos.models import Veiculo


# ---------------------- PÁGINA DO CALENDÁRIO ---------------------- #
@login_required
def calendar_view(request):
    """
    Renderiza a tela do calendário e envia os veículos ativos da
    unidade atual para o template (usado no <select> dentro de cada card).
    """
    unidade = get_unidade_atual(request)
    if not unidade:
        raise Http404("Unidade atual não definida para o usuário.")

    veiculos_ativos = Veiculo.objects.filter(
        unidade=unidade, ativo=True
    ).order_by("nome")

    return render(
        request,
        "programar_atividades/calendar.html",
        {
            "unidade": unidade,
            "veiculos_ativos": veiculos_ativos,
        },
    )


# ---------------------- FEED DO CALENDÁRIO (exemplo) ---------------------- #
@login_required
@require_GET
def events_feed(request):
    """
    Feed simples para o FullCalendar (mock).
    Depois você pode trocar por eventos reais do banco.
    """
    hoje = date.today().isoformat()
    data = [
        {"id": 1, "title": "Evento de teste", "start": hoje},
    ]
    return JsonResponse(data, safe=False)


# ---------------------- HELPERS PARA CAMPOS NUMÉRICOS ---------------------- #
def _num_or_none(v):
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


def _find_numeric_attr(obj, include_substr, exclude_substr=()):
    """
    Procura no objeto o primeiro atributo numérico cujo nome
    contém algum dos termos em include_substr e não contém exclude_substr.
    """
    inc = tuple(s.lower() for s in include_substr)
    exc = tuple(s.lower() for s in exclude_substr)

    # 1) tenta por atributos “conhecidos” primeiro (mais comuns)
    favoritos = [
        "qtd_alocada",
        "quantidade_alocada",
        "alocado",
        "quantidade",
        "alocado_unidade",
        "valor_alocado",
        "alocada",
        "executado",
        "qtd_executado",
        "quantidade_executada",
        "realizado",
        "feito",
        "progresso",
        "quantidade_total",
        "qtd_total",
        "alvo",
        "meta",
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

    # 2) varre demais atributos
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
def metas_disponiveis(request):
    """
    Metas da UNIDADE atual (opcional: ?atividade=<id>) com:
      - nome, atividade_nome, data_limite
      - alocado_unidade (somado por meta)
      - executado_unidade (somado por meta)
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
        if not meta:
            continue
        mid = getattr(meta, "id", None)
        if not mid:
            continue

        # --- alocado por alocação ---
        _, alocado_val = _find_numeric_attr(
            al,
            include_substr=("aloc", "qtd", "quant"),
            exclude_substr=("exec", "realiz", "feito"),
        )
        # --- executado por alocação ---
        _, executado_val = _find_numeric_attr(
            al,
            include_substr=("exec", "realiz", "feito"),
            exclude_substr=(),
        )

        if mid not in bucket:
            atividade = getattr(meta, "atividade", None)

            # total da meta (alvo)
            _, meta_total_val = _find_numeric_attr(
                meta,
                include_substr=("total", "alvo", "quant", "qtd", "meta"),
                exclude_substr=("exec", "realiz", "feito"),
            )

            # prazo
            data_limite = None
            for cand in ("data_limite", "deadline", "prazo", "limite"):
                if hasattr(meta, cand):
                    data_limite = getattr(meta, cand)
                    break

            bucket[mid] = {
                "id": mid,
                "nome": getattr(meta, "titulo", None)
                or getattr(meta, "nome", None)
                or str(meta),
                "atividade_id": getattr(atividade, "id", None),
                "atividade_nome": (
                    getattr(atividade, "nome", None)
                    or getattr(atividade, "titulo", None)
                    or (str(atividade) if atividade else None)
                ),
                "data_limite": data_limite.isoformat()
                if hasattr(data_limite, "isoformat")
                else data_limite,
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
@require_GET
@login_required
def servidores_disponiveis_para_data(request):
    """
    Retorna dois arrays para a data informada:
      - 'livres': servidores disponíveis
      - 'impedidos': servidores em descanso/impedimento (com motivo)
    """
    data_str = request.GET.get("data")
    if not data_str:
        return JsonResponse({"erro": "Data não informada"}, status=400)
    try:
        data = datetime.strptime(data_str, "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse({"erro": "Formato inválido da data"}, status=400)

    unidade_id = get_unidade_atual_id(request)
    if not unidade_id:
        return JsonResponse({"erro": "Unidade não definida"}, status=400)

    todos = Servidor.objects.filter(unidade_id=unidade_id, ativo=True).order_by("nome")

    # descansos que pegam a data -> gerar mapa servidor_id -> motivo (tipo)
    descansos_qs = (
        Descanso.objects.filter(
            servidor__unidade_id=unidade_id,
            data_inicio__lte=data,
            data_fim__gte=data,
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
