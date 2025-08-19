# controle_acesso/views.py (trecho relevante)
from django.contrib.auth.models import Group, Permission, User
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages

from .forms import PermissoesUsuarioForm

@login_required
@permission_required('auth.change_user', raise_exception=True)
def gerenciar_permissoes_usuario(request):
    user_id = request.GET.get('user_id')
    usuario = get_object_or_404(User, id=user_id)

    if request.method == "POST":
        form = PermissoesUsuarioForm(request.POST, instance=usuario)
        if form.is_valid():
            form.save()
            messages.success(request, "Permissões atualizadas com sucesso!")
            return redirect(f"{request.path}?user_id={usuario.id}")
    else:
        form = PermissoesUsuarioForm(instance=usuario)

    app_labels = {
        'admin': 'Administração',
        'auth': 'Autenticação e Autorização',
        'contenttypes': 'Tipos de Conteúdo',
        'core': 'Core',
        'sessions': 'Sessões'
    }
    model_labels = {
        'logentry': 'Entrada de log',
        'group': 'Grupo',
        'permission': 'Permissão',
        'user': 'Usuário',
        'contenttype': 'Tipo de conteúdo',
        'atividade': 'Atividade',
        'no': 'Unidade',
        'policy': 'Política',
        'userprofile': 'Perfil de usuário',
        'session': 'Sessão'
    }

    return render(request, "controle_acesso/gerenciar_permissoes.html", {
        "usuario": usuario,
        "form": form,
        "total": form.fields["permissoes"].queryset.count(),
        "app_labels": app_labels,
        "model_labels": model_labels,
    })

@permission_required("auth.change_group", raise_exception=True)
def editar_grupo(request, grupo_id):
    grupo = get_object_or_404(Group, pk=grupo_id)
    permissoes = Permission.objects.all().order_by("content_type__app_label", "codename")

    if request.method == "POST":
        selecionadas = request.POST.getlist("permissoes")
        grupo.permissions.set(selecionadas)
        messages.success(request, "Permissões do grupo atualizadas com sucesso!")
        return redirect("controle_acesso:editar_grupo", grupo_id=grupo.id)

    return render(
        request,
        "controle_acesso/editar_grupo.html",
        {
            "grupo": grupo,
            "permissoes": permissoes,
            "permissoes_grupo": grupo.permissions.all(),
        },
    )