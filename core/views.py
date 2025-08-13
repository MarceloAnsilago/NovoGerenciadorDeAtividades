# core/views.py

from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render
from django.http import JsonResponse
from .models import No
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.shortcuts import render, get_object_or_404
from django.contrib import messages
from django.contrib.auth.models import Group, Permission
from django.contrib.auth import get_user_model
from django.db import transaction
import secrets
from .forms import NovoPerfilForm
from django.contrib.auth import logout
from django.urls import reverse

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

User = get_user_model()

@login_required
@user_passes_test(lambda u: u.is_superuser)
@transaction.atomic
def novo_perfil(request):
    no_id = request.GET.get('no')
    no_selecionado = None
    if no_id:
        no_selecionado = get_object_or_404(No, id=no_id)

    if request.method == 'POST':
        form = NovoPerfilForm(request.POST)
        if form.is_valid():
            # 1) Grupo (perfil)
            group_name = form.cleaned_data['group_name'].strip()
            group, _ = Group.objects.get_or_create(name=group_name)

            # 2) Permissões (exemplo: core.No)
            perms = []
            def p(codename):
                try:
                    return Permission.objects.get(codename=codename)
                except Permission.DoesNotExist:
                    return None

            if form.cleaned_data['allow_view_no']:   perms.append(p('view_no'))
            if form.cleaned_data['allow_add_no']:    perms.append(p('add_no'))
            if form.cleaned_data['allow_change_no']: perms.append(p('change_no'))
            if form.cleaned_data['allow_delete_no']: perms.append(p('delete_no'))
            perms = [perm for perm in perms if perm]

            # Se quiser acumular permissões já existentes do grupo, use .add(*perms)
            # Aqui vamos definir exatamente as marcadas:
            if perms:
                group.permissions.set(perms)
            else:
                group.permissions.clear()

            # 3) Usuário + senha provisória
            username   = form.cleaned_data['username']
            first_name = form.cleaned_data.get('first_name', '')
            last_name  = form.cleaned_data.get('last_name', '')
            email      = form.cleaned_data['email']

            temp_password = secrets.token_urlsafe(8)  # ex.: 'q7T3Z...'
            user = User.objects.create_user(
                username=username,
                email=email,
                password=temp_password,
                first_name=first_name,
                last_name=last_name,
                is_active=True,
            )

            # 4) Vincular grupo e nó + força troca de senha
            user.groups.add(group)
            profile = getattr(user, 'profile', None)
            if profile:
                profile.must_change_password = True
                profile.no = no_selecionado
                profile.save(update_fields=['must_change_password', 'no'])

            messages.success(
                request,
                f"Perfil '{group.name}' preparado. Usuário '{user.username}' criado. "
                f"Senha provisória (mostrada uma única vez): {temp_password}"
            )
            return redirect('core:criar_perfil')
    else:
        form = NovoPerfilForm()

    contexto = {
        'form': form,
        'no_selecionado': no_selecionado,
    }
    return render(request, 'core/novo_perfil.html', contexto)

def sair(request):
    logout(request)
    return redirect(reverse('core:login'))