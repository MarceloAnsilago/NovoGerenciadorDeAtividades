from .models import No
from django.db.models import Q

def get_descendentes(no):
    descendentes = []

    filhos = No.objects.filter(parent=no)
    for filho in filhos:
        descendentes.append(filho)
        descendentes.extend(get_descendentes(filho))
    return descendentes

def contexto_unidade(request):
    unidades = []
    pode_assumir = False

    if request.user.is_authenticated:
        perfil = getattr(request.user, 'userprofile', None)
        if perfil and perfil.unidade:
            pode_assumir = request.user.has_perm('core.assumir_unidade')
            if pode_assumir:
                # Apenas a unidade atual e descendentes (sem subir)
                descendentes = get_descendentes(perfil.unidade)
                unidades = [perfil.unidade] + descendentes
                unidades = sorted(unidades, key=lambda x: x.nome)
            else:
                unidades = [perfil.unidade]

    return {
        'unidades_disponiveis': unidades,
        'pode_assumir_unidade': pode_assumir,
    }
