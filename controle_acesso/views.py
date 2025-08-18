from django.shortcuts import render

from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import permission_required

@permission_required("auth.view_group", raise_exception=True)

def gerenciar_permissoes(request):
    user_id = request.GET.get("user_id")
    user = get_object_or_404(User, id=user_id)

    return render(request, "controle_acesso/gerenciar_permissoes.html", {
        "usuario": user,
    })


@permission_required("auth.change_group", raise_exception=True)
def editar_grupo(request, grupo_id):
    grupo = get_object_or_404(Group, id=grupo_id)
    permissoes = Permission.objects.all().order_by("content_type__app_label", "codename")

    if request.method == "POST":
        selecionadas = request.POST.getlist("permissoes")
        grupo.permissions.set(selecionadas)
        return redirect("controle_acesso:gerenciar")

    return render(request, "controle_acesso/editar_grupo.html", {
        "grupo": grupo,
        "permissoes": permissoes,
        "permissoes_grupo": grupo.permissions.all(),
    })

