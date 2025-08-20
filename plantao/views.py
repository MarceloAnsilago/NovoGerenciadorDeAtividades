# plantao/views.py
from collections import defaultdict, Counter
from datetime import datetime
from itertools import chain
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from core.utils import get_unidade_atual_id
from servidores.models import Servidor
from descanso.models import Descanso




# plantao/views.py

from datetime import datetime, timedelta
from itertools import chain

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from core.utils import get_unidade_atual_id
from servidores.models import Servidor
from descanso.models import Descanso


def _prev_or_same_saturday(d):  # Mon=0..Sun=6; Saturday=5
    return d - timedelta(days=(d.weekday() - 5) % 7)

def _next_or_same_friday(d):    # Friday=4
    return d + timedelta(days=(4 - d.weekday()) % 7)

def _weeks_sat_to_fri(dt_ini, dt_fim):
    start = _prev_or_same_saturday(dt_ini)
    last  = _next_or_same_friday(dt_fim)
    weeks, cur = [], start
    while cur <= last:
        weeks.append((cur, cur + timedelta(days=6)))
        cur += timedelta(days=7)
    return weeks


@login_required
def lista_plantao(request):
    unidade_id = get_unidade_atual_id(request)

    data_inicial = (request.POST.get("data_inicial") or request.GET.get("data_inicial") or "")
    data_final   = (request.POST.get("data_final")   or request.GET.get("data_final")   or "")

    servidores_com_descanso = {}
    bloqueados = []
    grupos_data = []     # [{"index": i, "periodo": (ini,fim), "servidores": [...], "limite": int}]
    disp_options = []    # disponíveis
    exc_options  = []    # excluídos

    if not unidade_id:
        return render(request, "plantao/lista.html", {
            "data_inicial": data_inicial, "data_final": data_final,
            "servidores_com_descanso": servidores_com_descanso,
            "servidores_options": disp_options, "excluidos_options": exc_options,
            "bloqueados": bloqueados, "grupos": grupos_data,
        })

    if not (data_inicial and data_final):
        return render(request, "plantao/lista.html", {
            "data_inicial": data_inicial, "data_final": data_final,
            "servidores_com_descanso": servidores_com_descanso,
            "servidores_options": disp_options, "excluidos_options": exc_options,
            "bloqueados": bloqueados, "grupos": grupos_data,
        })

    # datas
    try:
        dt_ini = datetime.strptime(data_inicial, "%Y-%m-%d").date()
        dt_fim = datetime.strptime(data_final, "%Y-%m-%d").date()
    except ValueError:
        return render(request, "plantao/lista.html", {
            "data_inicial": "", "data_final": "",
            "servidores_com_descanso": servidores_com_descanso,
            "servidores_options": disp_options, "excluidos_options": exc_options,
            "bloqueados": bloqueados, "grupos": grupos_data,
        })

    if dt_fim < dt_ini:
        return render(request, "plantao/lista.html", {
            "data_inicial": data_inicial, "data_final": data_final,
            "servidores_com_descanso": servidores_com_descanso,
            "servidores_options": disp_options, "excluidos_options": exc_options,
            "bloqueados": bloqueados, "grupos": grupos_data,
        })

    # descansos de referência
    descansos = (Descanso.objects
                 .filter(servidor__unidade_id=unidade_id,
                         data_inicio__lte=dt_fim,
                         data_fim__gte=dt_ini)
                 .select_related("servidor", "servidor__unidade")
                 .order_by("servidor__nome", "data_inicio"))
    mapa_dd = defaultdict(list)
    for d in descansos:
        mapa_dd[d.servidor].append(d)
    servidores_com_descanso = dict(mapa_dd)

    # disponíveis = todos - descanso integral
    todos = Servidor.objects.filter(unidade_id=unidade_id).order_by("nome")
    bloqueados_ids = (Descanso.objects
                      .filter(servidor__in=todos, data_inicio__lte=dt_ini, data_fim__gte=dt_fim)
                      .values_list("servidor_id", flat=True).distinct())
    base_qs = todos.exclude(id__in=bloqueados_ids)
    bloqueados = list(todos.filter(id__in=bloqueados_ids))

    # semanas (Sáb→Sex) e limites por grupo vindos do request
    weeks = _weeks_sat_to_fri(dt_ini, dt_fim)
    limites = {}
    for i in range(1, len(weeks) + 1):
        raw = request.POST.get(f"qtd_{i}") or request.GET.get(f"qtd_{i}")
        try:
            lim = int(raw) if raw not in (None, "",) else 0
            if lim < 0: lim = 0
        except (TypeError, ValueError):
            lim = 0
        limites[i] = lim

    # grupos vindos do request (respeita limite por grupo)
    grupos_sel_ids = {}
    for i in range(1, len(weeks) + 1):
        ids = request.POST.getlist(f"grupo_{i}") or request.GET.getlist(f"grupo_{i}") or []
        lim = limites.get(i, 0)
        if lim > 0 and len(ids) > lim:
            ids = ids[:lim]
        try:
            grupos_sel_ids[i] = [int(x) for x in ids]
        except ValueError:
            grupos_sel_ids[i] = []

    # contagem para mostrar (N) em "Disponíveis"
    counts_map = Counter(chain.from_iterable(grupos_sel_ids.values()))

    # excluídos (escolha do usuário)
    excl_raw = request.POST.getlist("excluidos") or request.GET.getlist("excluidos") or []
    try:
        excl_ids = {int(x) for x in excl_raw}
    except ValueError:
        excl_ids = set()

    disp_qs = base_qs.exclude(id__in=excl_ids)
    exc_qs  = base_qs.filter(id__in=excl_ids)

    disp_options = [
        {
            "value": s.id,
            "label": s.nome,
            "count": counts_map.get(s.id, 0),
            "phone": (getattr(s, "telefone", None) or getattr(s, "celular", None) or ""),
        }
        for s in disp_qs
    ]

    # opcional — só se quiser mostrar/usar o phone na lista de excluídos
    exc_options = [
        {
            "value": s.id,
            "label": s.nome,
            "phone": (getattr(s, "telefone", None) or getattr(s, "celular", None) or ""),
        }
        for s in exc_qs
    ]

    # monta dados por grupo (ordem + limite)
    for i, (ini, fim) in enumerate(weeks, start=1):
        ids = grupos_sel_ids.get(i, [])
        objs = {s.id: s for s in Servidor.objects.filter(id__in=set(ids))}
        ordered = [objs[sid] for sid in ids if sid in objs]
        grupos_data.append({"index": i, "periodo": (ini, fim), "servidores": ordered, "limite": limites.get(i, 0)})

    return render(request, "plantao/lista.html", {
        "data_inicial": data_inicial, "data_final": data_final,
        "servidores_com_descanso": servidores_com_descanso,
        "servidores_options": disp_options, "excluidos_options": exc_options,
        "bloqueados": bloqueados, "grupos": grupos_data,
    })
@login_required
def servidores_em_descanso(request):
    """
    Página /plantao/descanso/servidores/ (lista plana de descansos no período).
    Útil como relatório auxiliar.
    """
    unidade_id = get_unidade_atual_id(request)
    data_inicial = request.GET.get("data_inicial") or ""
    data_final = request.GET.get("data_final") or ""
    qs = []

    if not unidade_id:
        messages.error(request, "Selecione uma unidade para consultar os descansos.")
    else:
        if data_inicial and data_final:
            try:
                dt_ini = datetime.strptime(data_inicial, "%Y-%m-%d").date()
                dt_fim = datetime.strptime(data_final, "%Y-%m-%d").date()
                if dt_fim < dt_ini:
                    messages.error(request, "A data final não pode ser anterior à data inicial.")
                else:
                    qs = (Descanso.objects
                          .filter(servidor__unidade_id=unidade_id,
                                  data_inicio__lte=dt_fim,
                                  data_fim__gte=dt_ini)
                          .select_related("servidor")
                          .order_by("servidor__nome", "data_inicio"))
            except ValueError:
                messages.error(request, "Datas inválidas. Use o seletor de data.")

    return render(request, "plantao/servidores_descanso.html", {
        "descansos": qs,
        "data_inicial": data_inicial,
        "data_final": data_final,
    })
