from .models import No
from django.db.models import Q

def contexto_unidade(request):
    unidades = []
    if request.user.is_authenticated:
        perfil = getattr(request.user, 'userprofile', None)
        if perfil:
            if request.user.has_perm('core.assumir_unidade'):
                # Pode assumir qualquer unidade
                unidades = No.objects.all().order_by('nome')
            else:
                # Apenas a unidade do perfil e suas filhas diretas
                unidades = (
                    No.objects.filter(Q(parent=perfil.unidade) | Q(id=perfil.unidade.id))
                    .order_by('nome')
                )
    return {
        'unidades_disponiveis': unidades
    }
