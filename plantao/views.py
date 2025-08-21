# plantao/views.py
from collections import defaultdict, Counter
from datetime import datetime
from itertools import chain
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.http import JsonResponse
from core.utils import get_unidade_atual_id
from servidores.models import Servidor
from descanso.models import Descanso
from django.views.decorators.http import require_GET



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
    grupos_data = []     # [{"index": i, "periodo": (ini,fim), "servidores": [...]}]
    disp_options = []    # disponíveis
    exc_options  = []    # excluídos

    # validações iniciais / render vazio
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

    # parse das datas
    try:
        dt_ini = datetime.strptime(data_inicial, "%Y-%m-%d").date()
        dt_fim = datetime.strptime(data_final, "%Y-%m-%d").date()
    except ValueError:
        messages.error(request, "Datas inválidas. Use o seletor de data no formato YYYY-MM-DD.")
        return render(request, "plantao/lista.html", {
            "data_inicial": "", "data_final": "",
            "servidores_com_descanso": servidores_com_descanso,
            "servidores_options": disp_options, "excluidos_options": exc_options,
            "bloqueados": bloqueados, "grupos": grupos_data,
        })

    if dt_fim < dt_ini:
        messages.error(request, "Data final não pode ser anterior à data inicial.")
        return render(request, "plantao/lista.html", {
            "data_inicial": data_inicial, "data_final": data_final,
            "servidores_com_descanso": servidores_com_descanso,
            "servidores_options": disp_options, "excluidos_options": exc_options,
            "bloqueados": bloqueados, "grupos": grupos_data,
        })

    # descansos de referência (para mostrar na tabela)
    descansos = (Descanso.objects
                 .filter(servidor__unidade_id=unidade_id,
                         data_inicio__lte=dt_fim,
                         data_fim__gte=dt_ini)
                 .select_related("servidor")
                 .order_by("servidor__nome", "data_inicio"))
    mapa_dd = defaultdict(list)
    for d in descansos:
        mapa_dd[d.servidor].append(d)
    servidores_com_descanso = dict(mapa_dd)

    # disponíveis = todos - descanso integral (bloqueados = descanso que cobre todo o período selecionado)
    todos = Servidor.objects.filter(unidade_id=unidade_id).order_by("nome")
    bloqueados_ids = (Descanso.objects
                      .filter(servidor__in=todos, data_inicio__lte=dt_ini, data_fim__gte=dt_fim)
                      .values_list("servidor_id", flat=True).distinct())
    base_qs = todos.exclude(id__in=bloqueados_ids)
    bloqueados = list(todos.filter(id__in=bloqueados_ids))

    # semanas (Sáb→Sex)
    weeks = _weeks_sat_to_fri(dt_ini, dt_fim)

    # grupos vindos do request (sem limites)
    grupos_sel_ids = {}
    for i in range(1, len(weeks) + 1):
        ids = request.POST.getlist(f"grupo_{i}") or request.GET.getlist(f"grupo_{i}") or []
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

    exc_options = [
        {
            "value": s.id,
            "label": s.nome,
            "phone": (getattr(s, "telefone", None) or getattr(s, "celular", None) or ""),
        }
        for s in exc_qs
    ]

    # validação servidor x descanso por grupo (servidores que conflitam)
    conflitos = defaultdict(list)  # {grupo_idx: [(Servidor, [Descanso,...]), ...]}
    for i, (ini, fim) in enumerate(weeks, start=1):
        ids = grupos_sel_ids.get(i, [])
        if not ids:
            continue
        # busca descansos que intersectam a semana atual para os servidores selecionados
        qs_conf = (Descanso.objects
                   .filter(servidor_id__in=ids, data_inicio__lte=fim, data_fim__gte=ini)
                   .select_related("servidor")
                   .order_by("servidor__nome", "data_inicio"))
        # agrupa por servidor
        mapa = defaultdict(list)
        for d in qs_conf:
            mapa[d.servidor].append(d)
        for servidor_obj, descansos_servidor in mapa.items():
            conflitos[i].append((servidor_obj, descansos_servidor))

    # se houver conflitos e a requisição for POST -> informar usuário e não prosseguir com "salvar"
    if request.method == "POST" and conflitos:
        # monta mensagens claras para o usuário
        mensagens = []
        for grupo_idx, itens in conflitos.items():
            ini, fim = weeks[grupo_idx - 1]
            periodo_str = f"{ini.strftime('%d/%m/%Y')} a {fim.strftime('%d/%m/%Y')}"
            for servidor_obj, descansos_servidor in itens:
                # pega resumo do descanso (tipo + intervalo)
                detalhes = "; ".join(
                    f"{(getattr(d, 'get_tipo_display', lambda: getattr(d, 'tipo', ''))() or getattr(d, 'tipo', ''))} "
                    f"({d.data_inicio.strftime('%d/%m/%Y')} a {d.data_fim.strftime('%d/%m/%Y')})"
                    for d in descansos_servidor
                )
                mensagens.append(f"{servidor_obj.nome} está em descanso no período {periodo_str}: {detalhes}")
        # juntamos em uma message do Django
        for m in mensagens:
            messages.error(request, m)

        # não prossegue com gravação — re-render com os dados preenchidos para correção manual pelo usuário
    else:
        # Se for POST e não houver conflitos, você pode implementar a lógica de gravação aqui.
        # Atualmente o código original não fazia persistência; se quiser que eu implemente o "salvar",
        # me diga como você quer armazenar a escala (modelo, relações).
        if request.method == "POST":
            messages.success(request, "Validação concluída — sem conflitos. (Implementar gravação se desejar.)")

    # monta dados por grupo (ordem)
    for i, (ini, fim) in enumerate(weeks, start=1):
        ids = grupos_sel_ids.get(i, [])
        objs = {s.id: s for s in Servidor.objects.filter(id__in=set(ids))}
        ordered = [objs[sid] for sid in ids if sid in objs]
        grupos_data.append({"index": i, "periodo": (ini, fim), "servidores": ordered})

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
    
@login_required
def verificar_descanso(request):
    servidor_id = request.GET.get("servidor_id")
    inicio = request.GET.get("inicio")
    fim = request.GET.get("fim")

    if not servidor_id or not inicio or not fim:
        return JsonResponse({"erro": "parâmetros inválidos: servidor_id,inicio,fim são obrigatórios"}, status=400)

    try:
        dt_ini = datetime.strptime(inicio, "%Y-%m-%d").date()
        dt_fim = datetime.strptime(fim, "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse({"erro": "formato de data inválido, use YYYY-MM-DD"}, status=400)

    try:
        servidor_id = int(servidor_id)
    except (ValueError, TypeError):
        return JsonResponse({"erro": "servidor_id inválido"}, status=400)

    qs = Descanso.objects.filter(
        servidor_id=servidor_id,
        data_inicio__lte=dt_fim,
        data_fim__gte=dt_ini,
    ).order_by("data_inicio")

    impedimentos = []
    for d in qs:
        tipo = None
        # se tiver choices e get_FIELD_display(), exibimos o label legível
        try:
            tipo = d.get_tipo_display()
        except Exception:
            tipo = getattr(d, "tipo", None)
        impedimentos.append({
            "data_inicio": d.data_inicio.isoformat(),
            "data_fim": d.data_fim.isoformat(),
            "tipo": tipo or "",
            "observacoes": (getattr(d, "observacoes", "") or "")[:200],  # evita payload gigante
        })

    if impedimentos:
        return JsonResponse({"bloqueado": True, "impedimentos": impedimentos})
    return JsonResponse({"bloqueado": False})