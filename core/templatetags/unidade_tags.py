from django import template
from core.models import No

register = template.Library()

@register.filter
def depth(unidade):
    nivel = 0
    atual = unidade
    while atual and atual.parent is not None:
        nivel += 1
        atual = atual.parent
    return nivel

@register.inclusion_tag('core/unidade_dropdown_item.html', takes_context=True)
def unidade_tree(context, unidades, contexto_atual):
    return {
        'unidades': unidades,
        'contexto_atual': contexto_atual,
        'request': context.get('request'),
    }