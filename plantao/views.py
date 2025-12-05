# stdlib
from types import SimpleNamespace
from datetime import datetime, timedelta, date
from collections import defaultdict, Counter
from itertools import chain
import traceback
import logging

# Django
from django.shortcuts import render, get_object_or_404, redirect
from django.template.loader import render_to_string
from django.http import JsonResponse, HttpResponse
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET, require_POST
from django.db import transaction
from django.urls import reverse
from django.utils.html import format_html
from django.conf import settings
from django.utils import timezone

# project utils / models
from core.utils import get_unidade_atual_id
from servidores.models import Servidor
from descanso.models import Descanso
from .models import Plantao, Semana, SemanaServidor
from .utils import verifica_conflito_plantao

def _get_plantao_respeitando_unidade(request, pk):
    """
    Retorna um Plantao (ou 404) aplicando filtro por unidade, se o model Plantao
    tiver o campo `unidade`. Staff vê tudo; usuários normais só veem plantões da unidade atual.
    """
    unidade_id = get_unidade_atual_id(request)
    # verifica se o model Plantao tem campo 'unidade' (compatibilidade)
    try:
        field_names = [f.name for f in Plantao._meta.fields]
    except Exception:
        field_names = []

    qs = Plantao.objects.all()
    if "unidade" in field_names or "unidade_id" in field_names:
        # se existe unidade no contexto e não é staff, filtra por unidade_id
        if unidade_id and not request.user.is_staff:
            qs = qs.filter(unidade_id=unidade_id)
        # se unidade_id None -> não aplicamos filtro (útil para admin ou contextos sem unidade)
    # get_object_or_404 aceita uma queryset como primeiro argumento
    return get_object_or_404(qs, pk=pk)




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

    # valores mínimos / vazios que devolvemos se abortar
    empty_context = {
        "data_inicial": data_inicial,
        "data_final": data_final,
        "servidores_com_descanso": {},
        "servidores_options": [],
        "excluidos_options": [],
        "bloqueados": [],
        "grupos": [],
        "conflito_abort": False,
    }

     # validações iniciais / render vazio
    if not unidade_id and not request.user.is_staff:
       return render(request, "plantao/lista.html", empty_context)

    if not (data_inicial and data_final):
        return render(request, "plantao/lista.html", empty_context)

    # parse das datas
    try:
        dt_ini = datetime.strptime(data_inicial, "%Y-%m-%d").date()
        dt_fim = datetime.strptime(data_final, "%Y-%m-%d").date()
    except ValueError:
        messages.error(request, "Datas inválidas. Use o seletor de data no formato YYYY-MM-DD.")
        return render(request, "plantao/lista.html", {**empty_context, "data_inicial": "", "data_final": ""})

    if dt_fim < dt_ini:
        messages.error(request, "Data final não pode ser anterior à data inicial.")
        return render(request, "plantao/lista.html", empty_context)

    # --- ler optional ignore_plantao (usado após salvar para não reportar o plantão recém-criado) ---
    ignore_raw = request.GET.get("ignore_plantao") or request.POST.get("ignore_plantao")
    ignore_plantao_id = None
    if ignore_raw:
        try:
            ignore_plantao_id = int(ignore_raw)
        except (ValueError, TypeError):
            ignore_plantao_id = None

    # -------------------------
    # VERIFICAÇÃO IMEDIATA DE CONFLITO DE PLANTÃO (antes de carregar descansos/servidores)
    # -------------------------
    # monta filtro de unidade se o model Plantao tiver campo de unidade
    unidade_filter = {}
    try:
        field_names = [f.name for f in Plantao._meta.fields]
    except Exception:
        field_names = []

    if "unidade" in field_names or "unidade_id" in field_names:
        unidade_filter = {"unidade_id": unidade_id}

    plantoes_qs = Plantao.objects.filter(
        inicio__lte=dt_fim,
        fim__gte=dt_ini,
        **unidade_filter,
    ).order_by("inicio")

    if ignore_plantao_id:
        plantoes_qs = plantoes_qs.exclude(pk=ignore_plantao_id)

    plantoes_conflitantes = plantoes_qs
    if plantoes_conflitantes.exists():
        itens = [f"{p.inicio.strftime('%d/%m/%Y')} a {p.fim.strftime('%d/%m/%Y')}" for p in plantoes_conflitantes]
        contador = len(itens)
        plural = "plantões" if contador != 1 else "plantão"
        periodo_sel = f"{dt_ini.strftime('%d/%m/%Y')} a {dt_fim.strftime('%d/%m/%Y')}"
        itens_txt = ", ".join(itens)

        msg = format_html(
            "Já existe(m) <strong>{}</strong> que conflitam com o período ({}) : {}.",
            f"{contador} {plural}", periodo_sel, itens_txt
        )
        messages.error(request, msg)

        return render(request, "plantao/lista.html", {
            "data_inicial": data_inicial,
            "data_final": data_final,
            "servidores_com_descanso": {},
            "servidores_options": [],
            "excluidos_options": [],
            "bloqueados": [],
            "grupos": [],
            "conflito_abort": True,
            "plantoes_conflitantes": plantoes_conflitantes,
        })

    # -------------------------------------------
    # dados para UI: descansos, disponíveis, weeks
    # -------------------------------------------
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

    todos = Servidor.objects.filter(unidade_id=unidade_id, ativo=True).order_by("nome")
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

    # ---------------------------------
    # validação servidor x descanso por grupo
    # ---------------------------------
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

    if request.method == "POST" and conflitos:
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

        # re-monta grupos_data igual ao bloco acima e retorna (abortando gravação)
        grupos_data = []
        for i, (ini, fim) in enumerate(weeks, start=1):
            ids = grupos_sel_ids.get(i, [])
            objs = {s.id: s for s in Servidor.objects.filter(id__in=set(ids), ativo=True)}
            ordered = [objs[sid] for sid in ids if sid in objs]
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

    # -------------------------
    # Se for POST e chegou aqui -> salva
    # -------------------------
    if request.method == "POST":
        # rechecagem final de conflito PLANTAO (race condition defense) --- filtra por unidade também
        race_qs = Plantao.objects.filter(inicio__lte=dt_fim, fim__gte=dt_ini, **unidade_filter)
        if race_qs.exists():
            messages.error(request, "Não foi possível salvar: já existe(m) plantão(ões) que conflitam com o período informado.")
            grupos_data = []
            for i, (ini, fim) in enumerate(weeks, start=1):
                ids = grupos_sel_ids.get(i, [])
                objs = {s.id: s for s in Servidor.objects.filter(id__in=set(ids), ativo=True)}
                ordered = [objs[sid] for sid in ids if sid in objs]
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

        # procede com gravação
        try:
            with transaction.atomic():
                observacao = request.POST.get("observacao", "")[:2000]

                # monta kwargs dinâmicos para criar o plantão incluindo unidade se o model suportar
                create_kwargs = {
                    "inicio": dt_ini,
                    "fim": dt_fim,
                    "criado_por": request.user,
                    "observacao": observacao,
                }
                if "unidade" in field_names or "unidade_id" in field_names:
                    create_kwargs["unidade_id"] = unidade_id

                plantao = Plantao.objects.create(**create_kwargs)

                for i, (ini, fim) in enumerate(weeks, start=1):
                    semana = Semana.objects.create(plantao=plantao, inicio=ini, fim=fim, ordem=i)
                    ids = grupos_sel_ids.get(i, [])
                    for ordem, sid in enumerate(ids, start=1):
                        try:
                            srv = Servidor.objects.get(pk=sid, ativo=True)
                            tel = getattr(srv, "telefone", None) or getattr(srv, "celular", None) or ""
                        except Servidor.DoesNotExist:
                            srv = None
                            tel = ""
                        SemanaServidor.objects.create(
                            semana=semana,
                            servidor_id=sid,
                            telefone_snapshot=tel,
                            ordem=ordem
                        )

                messages.success(request, f"Plantão salvo com sucesso: {dt_ini.strftime('%d/%m/%Y')} a {dt_fim.strftime('%d/%m/%Y')}")
                # redireciona para a lista sem parâmetros (estado inicial). a mensagem será mostrada na página recarregada.
                return redirect(reverse('plantao:lista_plantao'))

        except Exception as e:
            messages.error(request, "Erro ao salvar plantão: " + str(e))

    # monta dados por grupo (ordem) para render (caso GET ou POST abortado)
    grupos_data = []
    for i, (ini, fim) in enumerate(weeks, start=1):
        ids = grupos_sel_ids.get(i, [])
        objs = {s.id: s for s in Servidor.objects.filter(id__in=set(ids), ativo=True)}
        ordered = [objs[sid] for sid in ids if sid in objs]
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
        "conflito_abort": False,
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
    Página que lista plantões salvos. Suporta filtro por ano (GET ?ano=YYYY)
    e respeita a unidade atual (exceto para staff).
    """
    MONTH_NAMES_PT = (
        "Janeiro", "Fevereiro", "Março", "Abril",
        "Maio", "Junho", "Julho", "Agosto",
        "Setembro", "Outubro", "Novembro", "Dezembro",
    )
    # base queryset (ordenada)
    plantoes_base = Plantao.objects.order_by("-inicio")

    # aplica filtro de unidade se Plantao tem campo unidade e há unidade no contexto (exceto staff)
    try:
        field_names = [f.name for f in Plantao._meta.fields]
    except Exception:
        field_names = []

    unidade_id = get_unidade_atual_id(request)
    if ("unidade" in field_names or "unidade_id" in field_names) and unidade_id and not request.user.is_staff:
        plantoes_base = plantoes_base.filter(unidade_id=unidade_id)

    # --- construir lista de anos disponíveis (com base nos campos inicio/fim) ---
    years_set = set()
    # usa .dates para obter anos distintos. Se .dates não estiver disponível, cai para values_list
    try:
        for d in plantoes_base.dates("inicio", "year"):
            years_set.add(d.year)
        for d in plantoes_base.dates("fim", "year"):
            years_set.add(d.year)
    except Exception:
        # fallback: values_list sobre início/fim (menos elegante, mas funciona)
        ys = plantoes_base.values_list("inicio", flat=True)
        for dt in ys:
            if dt:
                years_set.add(dt.year)
        ys2 = plantoes_base.values_list("fim", flat=True)
        for dt in ys2:
            if dt:
                years_set.add(dt.year)

    years = sorted(years_set, reverse=True)

    # --- ler filtro de ano vindo do GET ---
    ano_raw = request.GET.get("ano") or ""
    ano_selected = None
    plantoes = plantoes_base
    if ano_raw:
        try:
            ano_selected = int(ano_raw)
            # seleciona plantões cujo período abrange o ano:
            # inicio.year <= ano_selected <= fim.year
            # implementado como dois filtros combinados (AND)
            plantoes = plantoes_base.filter(inicio__year__lte=ano_selected, fim__year__gte=ano_selected).order_by("-inicio")
        except (ValueError, TypeError):
            ano_selected = None
            # se valor inválido, ignoramos e mostramos tudo

    plantoes_list = list(plantoes)

    # agrupamento por mês (abas)
    month_map = {m: [] for m in range(1, 13)}
    for p in plantoes_list:
        ini = getattr(p, "inicio", None)
        fim = getattr(p, "fim", None)
        if not (ini and fim):
            continue

        # se filtrou por ano, restringe o intervalo ao ano selecionado
        if ano_selected:
            interval_start = date(ano_selected, 1, 1)
            interval_end = date(ano_selected, 12, 31)
            if fim < interval_start or ini > interval_end:
                continue
            ini = max(ini, interval_start)
            fim = min(fim, interval_end)

        cursor = date(ini.year, ini.month, 1)
        while cursor <= fim:
            month_map[cursor.month].append(p)
            # avança para o 1º dia do próximo mês
            if cursor.month == 12:
                cursor = date(cursor.year + 1, 1, 1)
            else:
                cursor = date(cursor.year, cursor.month + 1, 1)

    months_data = []
    months_with_items = []
    for idx, label in enumerate(MONTH_NAMES_PT, start=1):
        items = month_map.get(idx, [])
        if not items:
            continue  # exibe somente abas com plantão
        months_with_items.append(idx)
        months_data.append({
            "num": idx,
            "label": label,
            "plantoes": items,
            "count": len(items),
        })

    today_month_func = getattr(timezone, "localdate", None)
    today_month = today_month_func().month if callable(today_month_func) else datetime.today().month
    month_active = None
    if months_with_items:
        month_active = today_month if today_month in months_with_items else months_with_items[0]
        if month_active < 1 or month_active > 12:
            month_active = months_with_items[0]

    context = {
        "plantoes": plantoes_list,
        "months_data": months_data,
        "month_active": month_active,
        "years": years,
        "ano_selected": ano_selected,
    }
    return render(request, "plantao/ver_plantoes.html", context)

logger = logging.getLogger(__name__)
# a view tolerante
@login_required
def plantao_detalhe_fragment(request, pk):
    """
    Retorna um fragmento HTML para injeção via JS com a tabela de escala do plantão `pk`.
    Monta estruturas simples (SimpleNamespace) para evitar lookups dinâmicos quebrando templates.
    """
    try:
        plantao = _get_plantao_respeitando_unidade(request, pk)

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
    
    plantao = _get_plantao_respeitando_unidade(request, pk)
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
    plantao = _get_plantao_respeitando_unidade(request, pk)

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




@login_required
def servidores_por_intervalo(request):
    """
    GET params: start=YYYY-MM-DD, end=YYYY-MM-DD
    Retorna JSON: { ok: true, semanas: [ { inicio, fim, servidores: [{id,nome,telefone}] } ] }
    """
    start = request.GET.get('start')
    end   = request.GET.get('end')
    if not start or not end:
        return JsonResponse({"ok": False, "error": "start and end required"}, status=400)
    try:
        dt_start = datetime.strptime(start, "%Y-%m-%d").date()
        dt_end = datetime.strptime(end, "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse({"ok": False, "error": "invalid date format"}, status=400)

    # busca plantões que intersectam o intervalo
    unidade_id = get_unidade_atual_id(request)
    plantoes_qs = Plantao.objects.filter(inicio__lte=dt_end, fim__gte=dt_start)
    try:
        field_names = [f.name for f in Plantao._meta.fields]
    except Exception:
        field_names = []
    if ("unidade" in field_names or "unidade_id" in field_names) and unidade_id:
        plantoes_qs = plantoes_qs.filter(unidade_id=unidade_id)
    plantoes = plantoes_qs.order_by('inicio')
    if not plantoes.exists():
        return JsonResponse({"ok": True, "semanas": []})

    semanas_out = []
    for plantao in plantoes:
        # pega semanas relacionadas (tenta vários related_names)
        if hasattr(plantao, 'semanas'):
            semanas_qs = plantao.semanas.all().order_by('ordem', 'inicio')
        elif hasattr(plantao, 'semana_set'):
            semanas_qs = plantao.semana_set.all().order_by('ordem', 'inicio')
        else:
            semanas_qs = Semana.objects.filter(plantao=plantao).order_by('ordem', 'inicio')

        for semana in semanas_qs:
            # opcional: filtrar semanas que intersectam o intervalo pedido
            if semana.fim < dt_start or semana.inicio > dt_end:
                continue
            servidores = []
            # tenta vários relacionamentos
            if hasattr(semana, 'itens'):
                itens_qs = getattr(semana, 'itens').all()
            elif hasattr(semana, 'semanaservidor_set'):
                itens_qs = getattr(semana, 'semanaservidor_set').all()
            else:
                itens_qs = SemanaServidor.objects.filter(semana=semana)

            for item in itens_qs.order_by('ordem'):
                srv = getattr(item, 'servidor', None)
                nome = getattr(srv, 'nome', '') if srv else ''
                telefone_snapshot = getattr(item, 'telefone_snapshot', '') or ''
                telefone_servidor = getattr(srv, 'telefone', '') if srv else ''
                celular_servidor = getattr(srv, 'celular', '') if srv else ''
                telefone_final = telefone_snapshot or telefone_servidor or celular_servidor or ''
                servidores.append({
                    "id": getattr(srv, 'id', None),
                    "nome": nome,
                    "telefone": telefone_final,
                })
       
            semanas_out.append({
                "inicio": semana.inicio.isoformat(),
                "fim": semana.fim.isoformat(),
                "label": f"{semana.inicio.strftime('%d/%m/%Y')} → {semana.fim.strftime('%d/%m/%Y')}",
                "servidores": servidores
            })

    return JsonResponse({"ok": True, "semanas": semanas_out})
