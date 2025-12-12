# controle_acesso/templatetags/perm_utils.py
from django import template

register = template.Library()

@register.filter
def lookup(key, mapping):
    """Busca segura de dicionário no template."""
    if not isinstance(mapping, dict):
        return key
    return mapping.get(key, key)

@register.filter
def perm_label(name: str):
    """
    Traduz prefixos padrão do Django para PT-BR.
    Ex.: "Can add User" -> "Pode adicionar User"
    """
    if not isinstance(name, str):
        return name
    mapa = {
        "Can add": "Pode adicionar",
        "Can change": "Pode editar",
        "Can delete": "Pode excluir",
        "Can view": "Pode visualizar",
    }
    for en, pt in mapa.items():
        if name.startswith(en):
            return name.replace(en, pt, 1)
    return name


@register.filter
def perm_friendly(perm):
    """
    Gera uma descrição amigável para a permissão:
    - Usa codename para mapear ação/modelo (ex.: add_user -> Usuários — Criar).
    - Traduz especiais como 'assumir_unidade'.
    - Fallback: perm_label no nome padrão.
    """
    try:
        codename = getattr(perm, "codename", None) or ""
        model = getattr(getattr(perm, "content_type", None), "model", "") or ""
    except Exception:
        codename = ""
        model = ""

    # Mapa de ações
    action_map = {
        "add": "Criar",
        "change": "Editar",
        "delete": "Excluir",
        "view": "Visualizar",
    }

    # Mapa de modelos
    model_map = {
        "user": "Usuários",
        "group": "Grupos",
        "permission": "Permissões",
        "contenttype": "Tipos de conteúdo",
        "session": "Sessões",
        "userprofile": "Perfis de usuário",
        "policy": "Políticas",
        "no": "Unidades",
        "atividade": "Atividades",
        "meta": "Metas",
        "metaalocacao": "Alocações de metas",
        "progressometa": "Registros de progresso",
        "programacao": "Programações",
        "programacaoitem": "Itens de programação",
        "programacaoitemservidor": "Servidores na programação",
        "veiculo": "Veículos",
        "servidor": "Servidores",
    }

    # Caso especial: permissão customizada
    custom_map = {
        "assumir_unidade": "Assumir/alternar unidades",
    }
    if codename in custom_map:
        return custom_map[codename]

    if "_" in codename:
        action, _, _model = codename.partition("_")
        action_label = action_map.get(action)
        model_label = model_map.get(_model or model) or (_model or model or "").replace("_", " ").title()
        if action_label and model_label:
            return f"{model_label} — {action_label}"

    # Fallback: tenta traduzir o nome padrão
    return perm_label(getattr(perm, "name", str(perm)))
