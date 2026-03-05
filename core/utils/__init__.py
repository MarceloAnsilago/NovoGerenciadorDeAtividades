import secrets
import string

from .security import (
    assert_unidade,
    assert_unidade_scope,
    get_unidade_atual,
    get_unidade_atual_id,
    safe_next_url,
)


def gerar_senha_provisoria(tamanho=10):
    caracteres = string.ascii_letters + string.digits
    return "".join(secrets.choice(caracteres) for _ in range(tamanho))


def get_unidade_scope_ids(request, *, include_descendants=True):
    """
    Retorna a lista (ordenada) de IDs de unidades visíveis no contexto atual do usuário.
    - Se houver uma unidade assumida na sessão, utiliza-a como raiz.
    - Caso contrário, usa a unidade vinculada ao perfil do usuário (quando existir).
    - Sem contexto:
      - superuser: escopo global (None);
      - demais usuários: sem acesso (lista vazia).
    """
    raiz = get_unidade_atual(request)
    if raiz is None:
        user = getattr(request, "user", None)
        return None if getattr(user, "is_superuser", False) else []

    ids = {raiz.id}
    if not include_descendants:
        return [raiz.id]

    from core.models import No  # import tardio para evitar ciclos

    fronteira = [raiz.id]
    while fronteira:
        filhos = list(No.objects.filter(parent_id__in=fronteira).values_list("id", flat=True))
        fronteira = [fid for fid in filhos if fid not in ids]
        ids.update(fronteira)

    return sorted(ids)


# Compatibilidade com imports legados em apps que ainda usam o nome privado.
def _get_unidade_atual(request):
    return get_unidade_atual(request)
