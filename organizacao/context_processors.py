from django.contrib.auth.models import AnonymousUser
from .models import PerfilUsuario
from .utils import get_contexto, set_contexto

def contexto_vinculo(request):
    user = getattr(request, "user", AnonymousUser())
    ctx = None; vinculos = []; ctx_perms_full = set()

    if user.is_authenticated:
        vinculos = (PerfilUsuario.objects
                    .select_related("unidade","perfil_politica")
                    .filter(usuario=user).order_by("unidade__nome"))
        ctx = get_contexto(request)
        if ctx is None and request.session.get("vinculo_id"):
            request.session.pop("vinculo_id", None)
        if ctx is None and vinculos:
            ctx = vinculos[0]; set_contexto(request, ctx.id)

        if ctx and ctx.perfil_politica_id:
            pairs = ctx.perfil_politica.permissoes.values_list("content_type__app_label","codename")
            ctx_perms_full = {f"{app}.{code}" for app, code in pairs}

    return {"ctx_vinculo": ctx, "ctx_vinculos": vinculos, "ctx_perms_full": ctx_perms_full}
