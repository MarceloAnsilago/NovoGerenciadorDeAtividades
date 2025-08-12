from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .forms import PerfilUsuarioForm
from .models import PerfilUsuario

@login_required
@permission_required("organizacao.manage_policies", raise_exception=True)
def vinculos_lista(request):
    q = request.GET.get("q", "").strip()
    vinculos = (PerfilUsuario.objects
                .select_related("usuario", "unidade", "perfil_politica")
                .order_by("usuario__username", "unidade__nome"))
    if q:
        vinculos = vinculos.filter(unidade__nome__icontains=q) | \
                   vinculos.filter(usuario__username__icontains=q)
    return render(request, "organizacao/vinculos_list.html", {"vinculos": vinculos, "q": q})

@login_required
@permission_required("organizacao.manage_policies", raise_exception=True)
def vinculos_novo(request):
    form = PerfilUsuarioForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Vínculo criado com sucesso.")
        return redirect("organizacao:vinculos_home")
    return render(request, "organizacao/vinculos_form.html", {"form": form, "titulo": "Novo vínculo"})

@login_required
@permission_required("organizacao.manage_policies", raise_exception=True)
def vinculos_editar(request, pk: int):
    vinculo = get_object_or_404(PerfilUsuario, pk=pk)
    form = PerfilUsuarioForm(request.POST or None, instance=vinculo)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Vínculo atualizado com sucesso.")
        return redirect("organizacao:vinculos_home")
    return render(request, "organizacao/vinculos_form.html", {"form": form, "titulo": "Editar vínculo"})

@login_required
@permission_required("organizacao.manage_policies", raise_exception=True)
def vinculos_excluir(request, pk: int):
    vinculo = get_object_or_404(PerfilUsuario, pk=pk)
    if request.method == "POST":
        vinculo.delete()
        messages.success(request, "Vínculo excluído.")
        return redirect("organizacao:vinculos_home")
    return render(request, "organizacao/vinculos_excluir.html", {"v": vinculo})
