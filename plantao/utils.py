from datetime import timedelta
from django.contrib import messages
from django.shortcuts import render
from .models import Plantao

def gerar_plantao_semana_com_impedimentos(servidores, descansos_list, data_inicio, data_fim):
    """
    servidores: lista de objetos (qualquer objeto com atributo 'id' e __str__ útil)
    descansos_list: lista (ou queryset convertida para list) de objetos com atributos: servidor (ou servidor_id), inicio, fim
    data_inicio/data_fim: date
    Retorna: (tabela, impedimentos)
    """
    dias = []
    d = data_inicio
    while d <= data_fim:
        dias.append(d)
        d = d + timedelta(days=1)

    if not servidores:
        return None, ["Nenhum servidor selecionado."]

    n_serv = len(servidores)
    linhas = []
    impedimentos = []

    # transforma descansos_list em lista simples de dicts para consultas rápidas
    descansos_by_servidor = {}
    for dd in (descansos_list or []):
        # dd pode ter atributo servidor ou servidor_id
        sid = getattr(getattr(dd, "servidor", None), "id", None) or getattr(dd, "servidor_id", None)
        if sid is None:
            continue
        descansos_by_servidor.setdefault(sid, []).append(dd)

    for idx, s in enumerate(servidores):
        sid = getattr(s, "id", None)
        linha = {"servidor": s, "atrib": []}
        for dia in dias:
            in_desc = False
            for dd in descansos_by_servidor.get(sid, []):
                inicio = getattr(dd, "inicio", None)
                fim = getattr(dd, "fim", None)
                if inicio and fim and inicio <= dia <= fim:
                    in_desc = True
                    break
            if in_desc:
                linha["atrib"].append({"dia": dia, "status": "DESCANSO"})
                impedimentos.append(f"{s} em descanso em {dia.isoformat()}")
            else:
                dia_index = (dia - data_inicio).days
                if dia_index % n_serv == idx:
                    linha["atrib"].append({"dia": dia, "status": "SERVIÇO"})
                else:
                    linha["atrib"].append({"dia": dia, "status": ""})
        linhas.append(linha)

    tabela = [{"inicio": data_inicio, "fim": data_fim, "dias": dias, "linhas": linhas}]
    impedimentos = list(dict.fromkeys(impedimentos))  # dedupe mantendo ordem
    return tabela, impedimentos


def verifica_conflito_plantao(request, dt_ini, dt_fim, contexto):
    conflitos = Plantao.objects.filter(inicio__lte=dt_fim, fim__gte=dt_ini).order_by("inicio")
    if conflitos.exists():
        itens = [f"{p.inicio.strftime('%d/%m/%Y')} a {p.fim.strftime('%d/%m/%Y')}" for p in conflitos]
        contador = len(itens)
        plural = "plantões" if contador != 1 else "plantão"
        periodo_sel = f"{dt_ini.strftime('%d/%m/%Y')} a {dt_fim.strftime('%d/%m/%Y')}"
        itens_txt = ", ".join(itens)

        messages.error(request,
            f"Já existe(m) <strong>{contador} {plural}</strong> que conflitam com o período "
            f"(<strong>{periodo_sel}</strong>): {itens_txt}.")
        
        return render(request, "plantao/lista.html", contexto)

    return None