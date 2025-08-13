# core/views.py

from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render
from django.http import JsonResponse
from .models import No
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST



def dashboard(request):
    return render(request, 'core/dashboard.html')

@login_required
@user_passes_test(lambda u: u.is_superuser)
def admin_arvore(request):
    return render(request, 'core/admin_arvore.html')

def health(request):
    return JsonResponse({"status": "ok"})

@login_required
@user_passes_test(lambda u: u.is_superuser)
def nos_json(request):
    def node_to_dict(no):
        return {
            'id': no.id,
            'parent': '#' if no.parent is None else no.parent.id,
            'text': f"{no.nome} [{no.tipo}]",  # ← Aqui mostramos o tipo ao lado do nome
            'tipo': no.tipo  # Mantemos isso para uso interno no JS
        }

    nos = No.objects.all()
    data = [node_to_dict(no) for no in nos]
    return JsonResponse(data, safe=False)


@login_required
@user_passes_test(lambda u: u.is_superuser)
def admin_arvore(request):
    tem_estrutura = No.objects.exists()
    return render(request, 'core/admin_arvore.html', {'tem_estrutura': tem_estrutura})

@login_required
@user_passes_test(lambda u: u.is_superuser)
def criar_raiz(request):
    if request.method == "POST" and not No.objects.exists():
        No.objects.create(nome="Estrutura Principal", tipo="gerente")
    return redirect('core:admin_arvore')


@csrf_exempt
@require_POST
def ajax_criar_no(request):
    parent_id = request.POST.get('parent')
    nome = request.POST.get('nome', 'Novo nó')
    tipo = request.POST.get('tipo', 'indefinido')  # <- valor padrão aqui

    parent = No.objects.filter(id=parent_id).first() if parent_id else None
    novo_no = No.objects.create(nome=nome, tipo=tipo, parent=parent)

    return JsonResponse({'id': novo_no.id})

@csrf_exempt
@require_POST
def ajax_renomear_no(request):
    no_id = request.POST.get('id')
    novo_nome = request.POST.get('nome')

    try:
        no = No.objects.get(id=no_id)
        no.nome = novo_nome
        no.save()
        return JsonResponse({'status': 'ok'})
    except No.DoesNotExist:
        return JsonResponse({'status': 'erro', 'mensagem': 'Nó não encontrado'}, status=404)

@csrf_exempt
@require_POST
def ajax_excluir_no(request):
    no_id = request.POST.get('id')

    try:
        no = No.objects.get(id=no_id)
        no.delete()
        return JsonResponse({'status': 'ok'})
    except No.DoesNotExist:
        return JsonResponse({'status': 'erro', 'mensagem': 'Nó não encontrado'}, status=404)
    
@csrf_exempt
@require_POST
def ajax_definir_tipo(request):
    no_id = request.POST.get('id')
    tipo = request.POST.get('tipo')

    try:
        no = No.objects.get(id=no_id)
        no.tipo = tipo
        no.save()
        return JsonResponse({'status': 'ok'})
    except No.DoesNotExist:
        return JsonResponse({'status': 'erro', 'mensagem': 'Nó não encontrado'}, status=404)
    
@login_required
@user_passes_test(lambda u: u.is_superuser)
def criar_perfil(request):
    return render(request, 'core/criar_perfil.html')

@login_required
@user_passes_test(lambda u: u.is_superuser)
def criar_perfil(request):
    # Carrega todos os nós e organiza por parent
    nos = list(No.objects.select_related('parent').all())
    filhos_por_parent = {}
    for no in nos:
        filhos_por_parent.setdefault(no.parent_id, []).append(no)

    # Ordenação consistente (alfabética) por nome
    for lista in filhos_por_parent.values():
        lista.sort(key=lambda n: (n.nome or "").lower())

    def dfs(no, level, path_so_far, acumulador):
        path = path_so_far + [no.nome]
        acumulador.append({
            'id': no.id,
            'nome': no.nome,
            'tipo': no.tipo,
            'level': level,
            'indent_px': level * 18,  # indentação visual
            'path': " / ".join(path),
        })
        for filho in filhos_por_parent.get(no.id, []):
            dfs(filho, level + 1, path, acumulador)

    # Começa pelos nós raiz (parent=None)
    flat = []
    for raiz in filhos_por_parent.get(None, []):
        dfs(raiz, 0, [], flat)

    contexto = {
        'nos_planos': flat,  # lista flatten com level/indent/path
        'total_nos': len(flat),
    }
    return render(request, 'core/criar_perfil.html', contexto)