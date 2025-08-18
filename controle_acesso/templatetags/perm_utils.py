from django import template

register = template.Library()

@register.filter
def lookup(value, arg_dict):
    """
    Busca por chave em um dicionário no template.
    """
    return arg_dict.get(value, value)

@register.filter
def perm_label(name):
    """
    Traduz o nome da permissão para português.
    """
    traducoes = {
        "Can add": "Pode adicionar",
        "Can change": "Pode editar",
        "Can delete": "Pode excluir",
        "Can view": "Pode visualizar"
    }

    for ingles, portugues in traducoes.items():
        if name.startswith(ingles):
            return name.replace(ingles, portugues, 1)
    return name
