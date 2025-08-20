# core/utils.py
import random
import string

def gerar_senha_provisoria(tamanho=10):
    caracteres = string.ascii_letters + string.digits
    return ''.join(random.choice(caracteres) for _ in range(tamanho))


def _get_unidade_atual(request):
    """
    Retorna o objeto No (unidade) atual do usuário, priorizando o que estiver na sessão.
    Ordem de checagem:
      1) session['contexto'] = {'tipo': 'unidade', 'id': <int>} (ou 'unidade_id')
      2) session['contexto_atual'] (id direto)
      3) session['unidade_id'] (legado)
      4) perfil do usuário (user.userprofile/profile/perfil).unidade
    """
    # 1) contexto como dict
    ctx = request.session.get("contexto")
    if isinstance(ctx, dict) and ctx.get("tipo") == "unidade":
        uid = ctx.get("id") or ctx.get("unidade_id")
        if uid:
            from core.models import No  # import tardio para evitar circular
            return No.objects.filter(pk=uid).first()

    # 2) contexto_atual (id direto)
    uid = request.session.get("contexto_atual")
    if uid:
        try:
            from core.models import No
            return No.objects.filter(pk=int(uid)).first()
        except (TypeError, ValueError):
            pass

    # 3) unidade_id (legado)
    uid = request.session.get("unidade_id")
    if uid:
        try:
            from core.models import No
            return No.objects.filter(pk=int(uid)).first()
        except (TypeError, ValueError):
            pass

    # 4) fallback pelo perfil do usuário
    user = getattr(request, "user", None)
    if user:
        for attr in ("userprofile", "profile", "perfil"):
            obj = getattr(user, attr, None)
            if obj and getattr(obj, "unidade_id", None):
                return getattr(obj, "unidade", None)

    return None


def get_unidade_atual_id(request):
    """
    Retorna o ID (int) da unidade atual, ou None.
    """
    no = _get_unidade_atual(request)
    return no.pk if no else None


def get_unidade_atual(request):
    """
    Retorna o objeto No (unidade) atual, ou None.
    """
    return _get_unidade_atual(request)
