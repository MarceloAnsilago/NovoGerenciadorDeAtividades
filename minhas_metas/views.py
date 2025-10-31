from collections import defaultdict
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone
from django.conf import settings
from django.db.models import Sum, Count

from core.utils import get_unidade_atual
from metas.models import MetaAlocacao
from programar.models import Programacao, ProgramacaoItem, ProgramacaoItemServidor


def _parse_iso(value: str | None) -> date | None:
    if not value:
        return None
    try:
        year, month, day = map(int, value.split("-"))
        return date(year, month, day)
    except Exception:
        return None


@login_required
def minhas_metas_view(request):
    unidade = get_unidade_atual(request)
    if not unidade:
        messages.error(request, "Selecione uma unidade antes de ver as metas.")
        return redirect("core:dashboard")

    atividade_id = request.GET.get("atividade")
    status_filter = (request.GET.get("status") or "").lower()
    if status_filter not in {"concluidas", "pendentes"}:
        status_filter = ""

    alocacoes = (
        MetaAlocacao.objects
        .select_related("meta", "meta__atividade", "meta__criado_por", "meta__unidade_criadora")
        .annotate(realizado_unidade=Sum("progresso__quantidade"))
        .filter(unidade=unidade, meta__encerrada=False)
        .order_by("meta__data_limite", "meta__titulo")
    )
    if atividade_id:
        alocacoes = alocacoes.filter(meta__atividade_id=atividade_id)

    meta_ids = list(alocacoes.values_list("meta_id", flat=True))
    programadas_por_meta: dict[int, int] = {}
    if meta_ids:
        itens_stats = (
            ProgramacaoItem.objects
            .filter(meta_id__in=meta_ids)
            .values("meta_id")
            .annotate(total=Count("id"))
        )
        programadas_por_meta = {
            int(row["meta_id"]): int(row.get("total") or 0)
            for row in itens_stats
        }

    for aloc in alocacoes:
        meta_obj = getattr(aloc, "meta", None)
        if meta_obj and getattr(meta_obj, "id", None):
            setattr(meta_obj, "programadas_total", programadas_por_meta.get(int(meta_obj.id), 0))

    tem_filhos = unidade.filhos.exists()

    today = timezone.localdate()
    default_start = today.replace(day=1)

    start_qs = request.GET.get("start")
    end_qs = request.GET.get("end")

    dt_start = _parse_iso(start_qs) or default_start
    dt_end = _parse_iso(end_qs) or today
    if dt_end < dt_start:
        dt_end = dt_start

    progs_qs = Programacao.objects.filter(
        unidade_id=unidade.id,
        data__gte=dt_start,
        data__lte=dt_end,
    )

    expediente_meta_id = getattr(settings, "META_EXPEDIENTE_ID", None)

    itens_qs = (
        ProgramacaoItem.objects
        .select_related("programacao", "meta", "veiculo")
        .filter(programacao__in=progs_qs)
        .order_by("programacao__data", "id")
    )
    if expediente_meta_id:
        itens_qs = itens_qs.exclude(meta_id=expediente_meta_id)
    if atividade_id:
        itens_qs = itens_qs.filter(meta__atividade_id=atividade_id)
    if status_filter == "concluidas":
        itens_qs = itens_qs.filter(concluido=True)
    elif status_filter == "pendentes":
        itens_qs = itens_qs.filter(concluido=False)

    item_ids = list(itens_qs.values_list("id", flat=True))
    servidores_por_item: dict[int, list[str]] = defaultdict(list)
    if item_ids:
        links = (
            ProgramacaoItemServidor.objects
            .select_related("servidor")
            .filter(item_id__in=item_ids)
        )
        for link in links:
            servidor_nome = getattr(link.servidor, "nome", f"Servidor {link.servidor_id}")
            servidores_por_item[link.item_id].append(servidor_nome)

    andamento = []
    vistos = set()
    for item in itens_qs:
        if item.id in vistos:
            continue
        vistos.add(item.id)
        meta = getattr(item, "meta", None)
        programacao = getattr(item, "programacao", None)
        if not meta or not programacao:
            continue

        andamento.append({
            "item_id": item.id,
            "data": getattr(programacao, "data", None),
            "meta_id": getattr(meta, "id", None),
            "meta_titulo": getattr(meta, "display_titulo", None) or getattr(meta, "titulo", "(sem titulo)"),
            "atividade_nome": getattr(getattr(meta, "atividade", None), "titulo", None),
            "veiculo": getattr(getattr(item, "veiculo", None), "nome", "") or "",
            "servidores": servidores_por_item.get(item.id, []),
            "concluido": bool(getattr(item, "concluido", False)),
        })

    contexto = {
        "unidade": unidade,
        "alocacoes": alocacoes,
        "tem_filhos": tem_filhos,
        "andamento": andamento,
        "dt_start": dt_start,
        "dt_end": dt_end,
        "status_filter": status_filter,
    }
    return render(request, "minhas_metas/lista_metas.html", contexto)
