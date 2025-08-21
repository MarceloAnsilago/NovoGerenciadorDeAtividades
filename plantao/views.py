# stdlib
from types import SimpleNamespace
from datetime import datetime
from collections import defaultdict, Counter
from itertools import chain

# Django
from django.shortcuts import render, get_object_or_404, redirect
from django.template.loader import render_to_string
from django.http import JsonResponse, HttpResponse, HttpResponseForbidden, HttpResponseBadRequest
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET, require_POST
from django.db import transaction

# project utils / models
from core.utils import get_unidade_atual_id
from servidores.models import Servidor
from descanso.models import Descanso
from .models import Plantao, Semana, SemanaServidor

# plantao/views.py

from datetime import datetime, timedelta
from itertools import chain
# stdlib
from datetime import datetime
from collections import defaultdict, Counter
from itertools import chain

# Django
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.db import transaction

# utilidades do projeto
from core.utils import get_unidade_atual_id

# modelos externos ao app atual
from servidores.models import Servidor
from descanso.models import Descanso

# modelos deste app (plantao)
from .models import Plantao, Semana, SemanaServidor
import logging


import traceback
import sys
from django.conf import settings
from django.utils import timezone
from django.urls import reverse

from django.utils.safestring import mark_safe
from django.urls import reverse

# --- helpers de datas (já no seu código) ---
def _prev_or_same_saturday(d):  # Mon=0..Sun=6; Saturday=5
    from datetime import timedelta
    return d - timedelta(days=(d.weekday() - 5) % 7)

def _next_or_same_friday(d):    # Friday=4
    from datetime import timedelta
    return d + timedelta(days=(4 - d.weekday()) % 7)

def _weeks_sat_to_fri(dt_ini, dt_fim):
    from datetime import timedelta
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

    # variáveis que renderizamos no template
    servidores_com_descanso = {}
    bloqueados = []
    grupos_data = []     # [{"index": i, "periodo": (ini,fim), "servidores": [...]}]
    disp_options = []    # disponíveis (para select)
    exc_options  = []    # excluídos (para select)

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

    # -------------------------
    #  Verificação de conflitos
    # -------------------------
    plantoes_conflitantes = Plantao.objects.filter(inicio__lte=dt_fim, fim__gte=dt_ini).order_by("inicio")
    existe_conf_plantao = plantoes_conflitantes.exists()
    if existe_conf_plantao:
        itens = [f"{p.inicio.strftime('%d/%m/%Y')} a {p.fim.strftime('%d/%m/%Y')}" for p in plantoes_conflitantes]
        contador = plantoes_conflitantes.count()
        plural = "plantões" if contador != 1 else "plantão"
        periodo_sel = f"{dt_ini.strftime('%d/%m/%Y')} a {dt_fim.strftime('%d/%m/%Y')}"
        itens_txt = ", ".join(itens)

        # GET (filtrar) => aviso (warning)
        if request.method == "GET":
            messages.warning(request,
                f"Existe(m) <strong>{contador} {plural}</strong> que conflitam com o período selecionado "
                f"(<strong>{periodo_sel}</strong>): {itens_txt}.")
        # POST (tentar salvar) => erro e bloqueio
        else:
            messages.error(request,
                f"Não foi possível salvar: existe(m) <strong>{contador} {plural}</strong> que conflitam com o período "
                f"selecionado (<strong>{periodo_sel}</strong>): {itens_txt}.")

    # ---------------------------------
    # descansos de referência (para UI)
    # ---------------------------------
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

    # semanas (Sáb→Sex) - função helper _weeks_sat_to_fri deve existir no arquivo
    weeks = _weeks_sat_to_fri(dt_ini, dt_fim)

    # grupos vindos do request (sem limites aqui)
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

    # preparar opções para os selects JS/templates
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

    # validação servidor x descanso por grupo (servidores que conflitam com semanas)
    conflitos = defaultdict(list)  # {grupo_idx: [(Servidor, [Descanso,...]), ...]}
    for i, (ini, fim) in enumerate(weeks, start=1):
        ids = grupos_sel_ids.get(i, [])
        if not ids:
            continue
        qs_conf = (Descanso.objects
                   .filter(servidor_id__in=ids, data_inicio__lte=fim, data_fim__gte=ini)
                   .select_related("servidor")
                   .order_by("servidor__nome", "data_inicio"))
        mapa = defaultdict(list)
        for d in qs_conf:
            mapa[d.servidor].append(d)
        for servidor_obj, descansos_servidor in mapa.items():
            conflitos[i].append((servidor_obj, descansos_servidor))

    # ------------------------------------------
    # GRAVAÇÃO: se for POST e sem conflitos, grava
    # ------------------------------------------
    if request.method == "POST":
        # 1) conflitos de descanso por servidor -> bloqueia
        if conflitos:
            mensagens = []
            for grupo_idx, itens in conflitos.items():
                ini, fim = weeks[grupo_idx - 1]
                periodo_str = f"{ini.strftime('%d/%m/%Y')} a {fim.strftime('%d/%m/%Y')}"
                for servidor_obj, descansos_servidor in itens:
                    detalhes = "; ".join(
                        f"{(getattr(d, 'get_tipo_display', lambda: getattr(d, 'tipo', ''))() or getattr(d, 'tipo', ''))} "
                        f"({d.data_inicio.strftime('%d/%m/%Y')} a {d.data_fim.strftime('%d/%m/%Y')})"
                        for d in descansos_servidor
                    )
                    mensagens.append(f"{servidor_obj.nome} está em descanso no período {periodo_str}: {detalhes}")
            for m in mensagens:
                messages.error(request, m)

        # 2) re-checagem de plantões conflitantes (evita race condition)
        elif existe_conf_plantao:
            messages.error(request,
                "Não é possível salvar: já existe(m) plantão(ões) que conflitam com o período informado.")
        else:
            # 3) tudo ok -> cria plantão / semanas / itens dentro de transação
            try:
                with transaction.atomic():
                    observacao = request.POST.get("observacao", "")[:2000]
                    plantao = Plantao.objects.create(
                        inicio=dt_ini,
                        fim=dt_fim,
                        criado_por=request.user,
                        observacao=observacao,
                    )
                    # cria semanas e itens (preserva ordem conforme ids enviados)
                    for i, (ini, fim) in enumerate(weeks, start=1):
                        semana = Semana.objects.create(plantao=plantao, inicio=ini, fim=fim)
                        ids = grupos_sel_ids.get(i, [])
                        for ordem, sid in enumerate(ids, start=1):
                            # obter telefone do servidor (se existir)
                            try:
                                srv = Servidor.objects.get(pk=sid)
                                tel = getattr(srv, "telefone", None) or getattr(srv, "celular", None) or ""
                            except Servidor.DoesNotExist:
                                srv = None
                                tel = ""
                            # cria item de ligação (ajuste campos se seu model for diferente)
                            SemanaServidor.objects.create(
                                semana=semana,
                                servidor_id=sid,
                                telefone_snapshot=tel,
                                ordem=ordem
                            )
                # sucesso
                messages.success(request, f"Plantão salvo com sucesso: {dt_ini.strftime('%d/%m/%Y')} a {dt_fim.strftime('%d/%m/%Y')}")
                # redirect para evitar re-POST; preserva filtro no GET
                url = f"{reverse('plantao:lista_plantao')}?data_inicial={data_inicial}&data_final={data_final}"
                return redirect(url)
            except Exception as exc:
                messages.error(request, "Erro ao salvar plantão: " + str(exc))

    # monta dados por grupo (ordem) e garante atributos de telefone para os templates
    for i, (ini, fim) in enumerate(weeks, start=1):
        ids = grupos_sel_ids.get(i, [])
        objs = {s.id: s for s in Servidor.objects.filter(id__in=set(ids))}
        ordered = [objs[sid] for sid in ids if sid in objs]

        # garante atributos que o template espera (evita VariableDoesNotExist)
        for obj in ordered:
            tel = getattr(obj, "telefone", None) or getattr(obj, "celular", None) or ""
            setattr(obj, "telefone", tel)
            if not hasattr(obj, "celular"):
                setattr(obj, "celular", "")

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
    
@require_GET
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
        impedimentos.append({
            "data_inicio": d.data_inicio.isoformat(),
            "data_fim": d.data_fim.isoformat(),
            "tipo": d.get_tipo_display(),
            "observacoes": (d.observacoes or "")[:300],
        })

    if impedimentos:
        return JsonResponse({"bloqueado": True, "impedimentos": impedimentos})
    return JsonResponse({"bloqueado": False})


@login_required
def ver_plantoes(request):
    """
    Página que lista plantões salvos. A ação 'Abrir' carrega o fragmento com a tabela de escala abaixo.
    """
    plantoes = Plantao.objects.order_by("-inicio")
    return render(request, "plantao/ver_plantoes.html", {"plantoes": plantoes})

logger = logging.getLogger(__name__)
# a view tolerante
@login_required
def plantao_detalhe_fragment(request, pk):
    """
    Retorna um fragmento HTML para injeção via JS com a tabela de escala do plantão `pk`.
    Monta estruturas simples (SimpleNamespace) para evitar lookups dinâmicos quebrando templates.
    """
    try:
        plantao = get_object_or_404(Plantao, pk=pk)

        # pega queryset de semanas com fallback caso related_name diferente
        if hasattr(plantao, "semanas"):
            try:
                semanas_qs = plantao.semanas.all().order_by("ordem", "inicio")
            except Exception:
                # se 'ordem' não existir, tenta apenas por 'inicio'
                semanas_qs = plantao.semanas.all().order_by("inicio")
        elif hasattr(plantao, "semana_set"):
            try:
                semanas_qs = plantao.semana_set.all().order_by("ordem", "inicio")
            except Exception:
                semanas_qs = plantao.semana_set.all().order_by("inicio")
        else:
            semanas_qs = []

        grupos = []
        for i, semana in enumerate(semanas_qs, start=1):
            # detecta nome correto do relacionamento de itens e cria queryset seguro
            if hasattr(semana, "itens"):
                try:
                    itens_qs = semana.itens.all().order_by("ordem")
                except Exception:
                    itens_qs = semana.itens.all()
            elif hasattr(semana, "semanaservidor_set"):
                try:
                    itens_qs = semana.semanaservidor_set.all().order_by("ordem")
                except Exception:
                    itens_qs = semana.semanaservidor_set.all()
            else:
                itens_qs = []

            itens = []
            for item in itens_qs:
                servidor = getattr(item, "servidor", None)

                # snapshot do telefone no item (se existir), senão pega do servidor
                telefone_snapshot = getattr(item, "telefone_snapshot", "") or ""
                telefone_servidor = ""
                celular_servidor = ""
                nome_servidor = ""
                servidor_id = None

                if servidor is not None:
                    servidor_id = getattr(servidor, "id", None)
                    nome_servidor = getattr(servidor, "nome", "") or str(servidor)
                    telefone_servidor = getattr(servidor, "telefone", "") or ""
                    celular_servidor = getattr(servidor, "celular", "") or ""

                telefone_final = telefone_snapshot or telefone_servidor or celular_servidor or ""

                # SimpleNamespace funciona bem no template (atributos acessíveis via dot)
                servidor_obj = SimpleNamespace(
                    id=servidor_id,
                    nome=nome_servidor,
                    telefone=telefone_final,
                    celular=celular_servidor,
                    telefone_snapshot=telefone_snapshot,
                    servidor_original=servidor
                )

                itens.append(servidor_obj)

            # cuidado: certifique-se que semana tem attrs inicio/fim (ajuste se nome diferente)
            inicio = getattr(semana, "inicio", None)
            fim = getattr(semana, "fim", None)

            grupos.append({
                "index": i,
                "periodo": (inicio, fim),
                "servidores": itens,
            })

        html = render_to_string("partials/escala_tabela.html", {"grupos": grupos}, request=request)
        return HttpResponse(html, content_type="text/html")

    except Exception as exc:
        # registra stacktrace para debug no log
        logger.exception("Erro em plantao_detalhe_fragment pk=%s: %s", pk, exc)
        if getattr(settings, "DEBUG", False):
            tb = traceback.format_exc()
            return HttpResponse(f"<pre>{tb}</pre>", status=500, content_type="text/html")
        return HttpResponse("Erro ao carregar escala.", status=500)

@login_required
@require_POST
def plantao_excluir(request, pk):
    """
    Exclui um plantão. Permissão: quem criou ou staff. Retorna JSON.
    """
    plantao = get_object_or_404(Plantao, pk=pk)
    user = request.user

    # permite exclusão apenas pelo criador ou staff (ajuste conforme política)
    if plantao.criado_por and plantao.criado_por != user and not user.is_staff:
        return JsonResponse({"ok": False, "erro": "Você não tem permissão para excluir este plantão."}, status=403)

    try:
        plantao.delete()
        return JsonResponse({"ok": True})
    except Exception as e:
        # cuidado com exposição de detalhes em produção; aqui é útil para debug
        return JsonResponse({"ok": False, "erro": str(e)}, status=500)

    
@login_required
def plantao_imprimir(request, pk):
    plantao = get_object_or_404(Plantao, pk=pk)

    # monta os grupos (mesma lógica que antes)
    if hasattr(plantao, "semanas"):
        semanas_qs = plantao.semanas.order_by("ordem", "inicio").all()
    elif hasattr(plantao, "semana_set"):
        semanas_qs = plantao.semana_set.order_by("ordem", "inicio").all()
    else:
        semanas_qs = []

    grupos = []
    for i, semana in enumerate(semanas_qs, start=1):
        if hasattr(semana, "itens"):
            itens_qs = semana.itens.order_by("ordem").all()
        elif hasattr(semana, "semanaservidor_set"):
            itens_qs = semana.semanaservidor_set.order_by("ordem").all()
        else:
            itens_qs = []

        servidores = []
        for item in itens_qs:
            servidor = getattr(item, "servidor", None)
            nome = getattr(servidor, "nome", "") if servidor else ""
            telefone_snapshot = getattr(item, "telefone_snapshot", "") or ""
            telefone_servidor = getattr(servidor, "telefone", "") if servidor else ""
            celular_servidor = getattr(servidor, "celular", "") if servidor else ""
            telefone_final = telefone_snapshot or telefone_servidor or celular_servidor or ""
            servidores.append({
                "id": getattr(servidor, "id", None),
                "nome": nome,
                "telefone": telefone_final,
            })

        grupos.append({
            "index": i,
            "periodo": (semana.inicio, semana.fim),
            "servidores": servidores,
        })

    context = {"plantao": plantao, "grupos": grupos, "now": timezone.localtime()}

    # se for inline (fetch via AJAX/JS para injetar no layout), retorna somente o fragmento
    if request.GET.get("inline") in ("1", "true", "yes"):
        return render(request, "partials/escala_print_fragment.html", context)

    # caso contrário, retorna a página completa de impressão (como antes)
    return render(request, "plantao/print.html", context)