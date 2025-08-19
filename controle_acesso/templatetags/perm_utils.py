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
