from django import template

register = template.Library()

@register.filter
def depth(unidade):
    nivel = 0
    atual = unidade
    while atual.parent is not None:
        nivel += 1
        atual = atual.parent
    return nivel