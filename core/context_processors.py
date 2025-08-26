# core/context_processors.py
from .models import No

def _collect_subtree_ids(root_id):
    """Coleta IDs do root + todos descendentes (iterativo, várias queries por nível)."""
    ids = {root_id}
    frontier = [root_id]
    while frontier:
        children_qs = No.objects.filter(parent_id__in=frontier).values_list('id', flat=True)
        frontier = [cid for cid in children_qs if cid not in ids]
        ids.update(frontier)
    return ids

def _build_tree(nodes_qs, root_id):
    """Recebe queryset (ou lista) de nós e monta .children em cada nó (lista ordenada por nome)."""
    nodes = list(nodes_qs)
    by_id = {n.id: n for n in nodes}
    children_map = {}
    for n in nodes:
        children_map.setdefault(n.parent_id, []).append(n)

    # ordenar filhos por nome
    for pid, childs in children_map.items():
        children_map[pid] = sorted(childs, key=lambda x: x.nome.lower())

    # anexar atributo `children` a cada nó presente
    for n in nodes:
        n.children = children_map.get(n.id, [])

    # retornar o nó root (caso não exista, retorna lista vazia)
    root = by_id.get(root_id)
    return root

def contexto_unidade(request):
    unidades = []
    pode_assumir = False

    if request.user.is_authenticated:
        perfil = getattr(request.user, 'userprofile', None)
        if perfil and perfil.unidade:
            pode_assumir = request.user.has_perm('core.assumir_unidade')
            if pode_assumir:
                # coletar ids do root + descendentes
                root_id = perfil.unidade.id
                ids = _collect_subtree_ids(root_id)
                # carregar todos os nós de uma vez (reduz queries)
                nodes_qs = No.objects.filter(id__in=ids).order_by('nome')
                root = _build_tree(nodes_qs, root_id)
                unidades = [root] if root is not None else []
            else:
                # sem permissão: apenas a própria unidade (sem filhos)
                unidade = perfil.unidade
                unidade.children = []  # padroniza interface para o template
                unidades = [unidade]

    return {
        'unidades_disponiveis': unidades,
        'pode_assumir_unidade': pode_assumir,
    }
