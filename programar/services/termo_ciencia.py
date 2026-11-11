"""Dados do termo de ciência, limitados ao período e à unidade do relatório."""
from collections import defaultdict
from datetime import timedelta

from django.conf import settings

from programar.models import Programacao, ProgramacaoItem, ProgramacaoItemServidor


def montar_termo_ciencia(unidade_id, inicio, fim, *, status_para_data, expediente_desativado):
    if not unidade_id or not inicio or not fim or fim < inicio:
        return []

    programacoes = {
        p.data: p
        for p in Programacao.objects.filter(
            unidade_id=unidade_id, data__gte=inicio, data__lte=fim
        )
    }
    itens = list(
        ProgramacaoItem.objects.filter(
            programacao__unidade_id=unidade_id,
            programacao__data__gte=inicio,
            programacao__data__lte=fim,
            cancelada=False,
        ).select_related("programacao", "meta__atividade")
    )
    por_dia = defaultdict(list)
    for item in itens:
        por_dia[item.programacao.data].append(item)
    vinculos = defaultdict(list)
    if itens:
        for vinculo in ProgramacaoItemServidor.objects.filter(
            item_id__in=[item.pk for item in itens],
            servidor__ativo=True,
        ).select_related("servidor"):
            if vinculo.servidor.ativo:
                vinculos[vinculo.item_id].append(vinculo.servidor)

    servidores = {}
    expediente_nome = "Expediente administrativo"
    meta_expediente_id = str(getattr(settings, "META_EXPEDIENTE_ID", ""))

    def adicionar(sid, nome, matricula, atividade, dia):
        if not sid:
            return
        servidor = servidores.setdefault(
            sid, {"id": sid, "nome": nome, "matricula": matricula or "", "atividades": {}}
        )
        if matricula and not servidor["matricula"]:
            servidor["matricula"] = matricula
        servidor["atividades"].setdefault(atividade, set()).add(dia)

    dia = inicio
    while dia <= fim:
        itens_dia = por_dia[dia]
        # Assim como a programação impressa, não cria expediente em fins de
        # semana sem atividades. Feriados não recebem expediente automático.
        if dia.weekday() >= 5 and not itens_dia:
            dia += timedelta(days=1)
            continue

        livres, impedidos, feriados, _plantao = status_para_data(unidade_id, dia)
        prog = programacoes.get(dia)
        sem_expediente = bool(
            feriados or (prog and expediente_desativado(prog.observacao))
        )
        alocados = set()
        for item in itens_dia:
            # Defesa adicional para consumidores que forneçam itens em memória.
            if item.cancelada:
                continue
            nome = item.meta.display_titulo
            is_expediente = (
                str(item.meta_id) == meta_expediente_id
                or nome.strip().casefold() in {
                    "expediente", "expediente adm", "expediente adm.", "expediente administrativo"
                }
            )
            for servidor in vinculos[item.pk]:
                alocados.add(str(servidor.pk))
                if is_expediente and sem_expediente:
                    continue
                adicionar(
                    servidor.pk, servidor.nome, servidor.matricula,
                    expediente_nome if is_expediente else nome, dia,
                )

        if not sem_expediente:
            impedidos_ids = {str(s["id"]) for s in impedidos}
            for servidor in livres:
                if str(servidor["id"]) not in alocados | impedidos_ids:
                    adicionar(
                        servidor["id"], servidor["nome"], servidor.get("matricula"),
                        expediente_nome, dia,
                    )
        dia += timedelta(days=1)

    resultado = []
    dias_semana = ("seg.", "ter.", "qua.", "qui.", "sex.", "sáb.", "dom.")
    for servidor in sorted(servidores.values(), key=lambda s: (s["nome"].casefold(), str(s["id"]))):
        atividades = []
        for nome, datas in sorted(
            servidor["atividades"].items(),
            key=lambda par: (par[0] != expediente_nome, par[0].casefold()),
        ):
            atividades.append({
                "nome": nome,
                "dias": [
                    f"{dias_semana[data.weekday()]} {data:%d/%m/%Y}"
                    for data in sorted(datas)
                ],
            })
        resultado.append({**servidor, "atividades": atividades})
    return resultado
