from django.shortcuts import render

# Create your views here.
# organizacao/views.py

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.models import User
from django.shortcuts import render, redirect, get_object_or_404
from .forms import UsuarioCreateForm

@login_required
def dashboard(request):
    return render(request, "organizacao/dashboard.html")

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.models import User
from django.shortcuts import render, redirect, get_object_or_404
from .forms import UsuarioCreateForm

@login_required
@permission_required("auth.add_user", raise_exception=True)
def usuarios_lista(request):
    q = request.GET.get("q", "").strip()
    users = User.objects.all().order_by("username")
    if q:
        users = users.filter(username__icontains=q) | users.filter(first_name__icontains=q) | users.filter(email__icontains=q)
    return render(request, "organizacao/usuarios_list.html", {"users": users, "q": q})

@login_required
@permission_required("auth.add_user", raise_exception=True)
def usuarios_novo(request):
    form = UsuarioCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Usuário criado com sucesso.")
        return redirect("organizacao:usuarios_lista")
    return render(request, "organizacao/usuarios_form.html", {"form": form, "titulo": "Novo usuário"})
