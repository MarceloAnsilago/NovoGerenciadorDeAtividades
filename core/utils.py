# utils.py
import random
import string

def gerar_senha_provisoria(tamanho=10):
    caracteres = string.ascii_letters + string.digits
    return ''.join(random.choice(caracteres) for _ in range(tamanho))


def _get_unidade_atual(request):
    """
    Obtém a unidade atual (prioriza o contexto da sessão).
    - Session: 'contexto_atual' (usado no core) ou 'unidade_id' (fallback antigo)
    - Fallback: user.userprofile.unidade (ou aliases)
    """
    uid = request.session.get("contexto_atual") or request.session.get("unidade_id")
    if uid:
        from core.models import No  # import tardio evita circular
        return No.objects.filter(pk=uid).first()

    user = request.user
    for attr in ("userprofile", "profile", "perfil"):
        obj = getattr(user, attr, None)
        if obj and getattr(obj, "unidade_id", None):
            return obj.unidade

    return None