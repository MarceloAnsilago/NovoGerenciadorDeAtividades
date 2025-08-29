# programar_atividades/views.py
from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from core.utils import get_unidade_atual
from metas.models import MetaAlocacao
from decimal import Decimal

from django.http import JsonResponse
from datetime import datetime
from core.utils import get_unidade_atual_id
from servidores.models import Servidor
from plantao.models import Plantao
from descanso.models import Descanso

from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET

@login_required
def calendar_view(request):
    """Renderiza a tela do calendário."""
    return render(request, "programar_atividades/calendar.html")

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
        "qtd_alocada", "quantidade_alocada", "alocado", "quantidade",
        "alocado_unidade", "valor_alocado", "alocada",
        "executado", "qtd_executado", "quantidade_executada",
        "realizado", "feito", "progresso",
        "quantidade_total", "qtd_total", "alvo", "meta",
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
        MetaAlocacao.objects
        .select_related("meta", "meta__atividade")
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
                "nome": getattr(meta, "titulo", None) or getattr(meta, "nome", None) or str(meta),
                "atividade_id": getattr(atividade, "id", None),
                "atividade_nome": (
                    getattr(atividade, "nome", None)
                    or getattr(atividade, "titulo", None)
                    or (str(atividade) if atividade else None)
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


@require_GET
@login_required
def servidores_disponiveis_para_data(request):
    from datetime import datetime
    from core.utils import get_unidade_atual_id
    from servidores.models import Servidor
    from descanso.models import Descanso
    from django.http import JsonResponse

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

    descansando_ids = set(
        Descanso.objects
            .filter(
                servidor__unidade_id=unidade_id,
                data_inicio__lte=data,
                data_fim__gte=data
            )
            .values_list("servidor_id", flat=True)
    )

    livres = todos.exclude(id__in=descansando_ids)
    impedidos = todos.filter(id__in=descansando_ids)

    def map_servidor(s):
        return {
            "id": s.id,
            "nome": s.nome,
            "telefone": s.telefone or s.celular or "",
        }

    return JsonResponse({
        "livres": [map_servidor(s) for s in livres],
        "impedidos": [map_servidor(s) for s in impedidos],
    })
