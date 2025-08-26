# core/views.py

import random
import string

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required, user_passes_test, permission_required
from django.contrib.auth import authenticate, logout, login as auth_login, get_user_model
from django.contrib.auth.forms import SetPasswordForm
from django.utils.http import url_has_allowed_host_and_scheme
from django.contrib.auth.models import Group
from django.views.generic import TemplateView
from django.urls import reverse

from .models import No, UserProfile  # No (Unidade) e UserProfile
from .models import No as Unidade
# from .forms import UserProfileForm  # removido: não utilizado

# Inicializa o modelo de usuário
User = get_user_model()

# ============ DASHBOARD ============

@login_required
def home(request):
    return render(request, "core/home.html")


# ============ ÁRVORE (jsTree) ============

@user_passes_test(lambda u: u.is_staff)
@login_required
def admin_arvore(request):
    tem_unidades = Unidade.objects.exists()
    return render(request, "core/admin_arvore.html", {"tem_unidades": tem_unidades})


@login_required
def nos_list(request):
    dados = [no.to_jstree() for no in Unidade.objects.all()]
    return JsonResponse(dados, safe=False)


@require_POST
@login_required
@user_passes_test(lambda u: u.is_staff)
def nos_criar(request):
    nome = request.POST.get('nome', 'Novo Nó')
    parent_id = request.POST.get('parent')
    parent = Unidade.objects.filter(id=parent_id).first() if parent_id else None
    no = Unidade.objects.create(nome=nome, parent=parent)
    return JsonResponse(no.to_jstree())


@require_POST
@login_required
@user_passes_test(lambda u: u.is_staff)
def nos_renomear(request, pk):
    no = get_object_or_404(Unidade, pk=pk)
    novo_nome = request.POST.get('nome')
    if not novo_nome:
        return HttpResponseBadRequest('Nome inválido')
    no.nome = novo_nome
    no.save()
    return JsonResponse({'status': 'ok'})


@require_POST
@login_required
@user_passes_test(lambda u: u.is_staff)
def nos_mover(request, pk):
    no = get_object_or_404(Unidade, pk=pk)
    novo_parent_id = request.POST.get('parent')
    novo_parent = Unidade.objects.filter(id=novo_parent_id).first() if novo_parent_id else None
    no.parent = novo_parent
    no.save()
    return JsonResponse({'status': 'ok'})


@require_POST
@login_required
@user_passes_test(lambda u: u.is_staff)
def nos_deletar(request, pk):
    no = get_object_or_404(Unidade, pk=pk)
    no.delete()
    return JsonResponse({'status': 'ok'})


# ============ PERFIS ============

@login_required
def perfis(request):
    unidades = No.objects.select_related('parent').all().order_by('parent_id', 'nome')
    return render(request, 'core/perfis.html', {'unidades': unidades})


@login_required
@permission_required('core.add_userprofile', raise_exception=True)
def criar_perfil(request):
    if request.method != "POST":
        return JsonResponse({"status": "erro", "erro": "Método não permitido."}, status=405)

    try:
        username = request.POST.get("username")
        email = request.POST.get("email")
        is_staff = bool(request.POST.get("is_staff"))
        unidade_id = request.POST.get("unidade_id")

        if not (username and email and unidade_id):
            return JsonResponse({"status": "erro", "erro": "Dados incompletos."}, status=400)

        if User.objects.filter(username=username).exists():
            return JsonResponse({"status": "erro", "erro": "Já existe um usuário com esse nome."}, status=400)

        # Gera senha provisória
        senha_provisoria = ''.join(random.choices(string.ascii_letters + string.digits, k=8))

        # Cria usuário SEM senha real
        user = User(username=username, email=email, is_staff=is_staff)
        user.set_unusable_password()
        user.save()

        # Vincula unidade
        unidade = get_object_or_404(No, pk=unidade_id)
        UserProfile.objects.create(
            user=user,
            unidade=unidade,
            senha_provisoria=senha_provisoria,
            ativado=False
        )

        return JsonResponse({
            "status": "ok",
            "username": username,
            "senha_provisoria": senha_provisoria
        })

    except Exception as e:
        return JsonResponse({"status": "erro", "erro": str(e)}, status=500)


@require_POST
@login_required
@permission_required('core.add_userprofile', raise_exception=True)
def excluir_perfil(request, user_id):
    user = get_object_or_404(User, id=user_id)

    try:
        user.delete()
        return JsonResponse({"status": "excluido"})
    except Exception as e:
        try:
            user.is_active = False
            user.save()
            return JsonResponse({"status": "inativado"})
        except Exception as e2:
            return JsonResponse({"status": "erro", "erro": str(e2)}, status=500)


@require_POST
@login_required
@permission_required('core.change_userprofile', raise_exception=True)
def redefinir_senha(request, user_id):
    user = get_object_or_404(User, pk=user_id)

    try:
        profile = user.userprofile
    except UserProfile.DoesNotExist:
        return JsonResponse({"status": "erro", "erro": "Perfil não encontrado."}, status=404)

    nova_senha = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    user.set_unusable_password()
    user.save()

    profile.senha_provisoria = nova_senha
    profile.ativado = False
    profile.save()

    return JsonResponse({
        "status": "ok",
        "username": user.username,
        "senha_provisoria": nova_senha
    })


# ============ PRIMEIRO ACESSO / TROCA DE SENHA ============

@login_required
def primeiro_acesso_token_view(request):
    context = {}
    if request.method == 'POST':
        username = request.POST.get('username')
        token = request.POST.get('token')
        try:
            user = User.objects.get(username=username)
            profile = user.userprofile
            if profile.senha_provisoria == token and not profile.ativado:
                request.session['troca_user_id'] = user.id
                return redirect('core:trocar_senha_primeiro_acesso')
            context['erro'] = "Token inválido ou já utilizado."
        except User.DoesNotExist:
            context['erro'] = "Usuário não encontrado."
    return render(request, 'primeiro_acesso_verificar.html', context)


def trocar_senha_primeiro_acesso(request):
    user_id = request.session.get('troca_user_id')
    if not user_id:
        messages.error(request, "Sessão de primeiro acesso expirada ou inválida.")
        return redirect('core:login')

    user = User.objects.get(id=user_id)

    if request.method == 'POST':
        form = SetPasswordForm(user, request.POST)
        if form.is_valid():
            form.save()
            profile = user.userprofile
            profile.ativado = True
            profile.senha_provisoria = None
            profile.save()

            del request.session['troca_user_id']
            auth_login(request, user)
            messages.success(request, "Senha alterada com sucesso! Bem-vindo(a) ao sistema.")
            return redirect('core:dashboard')
        messages.error(request, "Erro ao alterar senha. Verifique os campos.")
    else:
        form = SetPasswordForm(user)

    return render(request, 'core/primeiro_acesso_trocar_senha.html', {'form': form})


# ============ AUTENTICAÇÃO ============

def login_view(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)
        if user is not None:
            auth_login(request, user)
            return redirect("core:dashboard")

        try:
            user_obj = User.objects.get(username=username)
            profile = user_obj.userprofile
        except (User.DoesNotExist, UserProfile.DoesNotExist):
            messages.error(request, "Usuário ou senha inválidos.")
            return render(request, "core/login.html")

        if profile.senha_provisoria == password and not profile.ativado:
            request.session['troca_user_id'] = user_obj.id
            return redirect('core:trocar_senha_primeiro_acesso')

        messages.error(request, "Usuário ou senha inválidos.")
        return render(request, "core/login.html")

    return render(request, "core/login.html")


def logout_view(request):
    logout(request)
    messages.success(request, "Você saiu da sessão.")
    return redirect("core:login")


# ============ CONTEXTO (SP6) ============

@login_required
@permission_required('core.assumir_unidade', raise_exception=True)
def assumir_unidade(request, unidade_id=None, id=None):
    pk = unidade_id or id
    unidade = get_object_or_404(No, pk=pk)
    request.session['contexto_atual'] = unidade.id
    request.session['contexto_nome'] = unidade.nome
    messages.success(request, f'Unidade alterada para: {unidade.nome}')

    next_url = request.GET.get('next')
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect(reverse('core:dashboard'))


@login_required
def voltar_contexto(request):
    request.session.pop("contexto_atual", None)
    request.session.pop("contexto_nome", None)
    messages.success(request, "Contexto restaurado para a unidade original.")
    return redirect(request.META.get("HTTP_REFERER", "core:dashboard"))


class DashboardView(TemplateView):
    template_name = "core/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        total_usuarios = User.objects.count()
        total_perfis = Group.objects.count()
        total_nos = No.objects.count()

        ctx["metrics"] = [
            {
                "label": "Usuários",
                "value": total_usuarios,
                "icon": "bi-people",
                "bg": "bg-primary-subtle",
                "fg": "text-primary",
                "link_name": "core:perfis",
            },
            {
                "label": "Perfis",
                "value": total_perfis,
                "icon": "bi-person-badge",
                "bg": "bg-success-subtle",
                "fg": "text-success",
                "link_name": "core:perfis",
            },
            {
                "label": "Unidades / Estrutura",
                "value": total_nos,
                "icon": "bi-diagram-3",
                "bg": "bg-warning-subtle",
                "fg": "text-warning",
                "link_name": "core:admin_arvore",
            },
        ]

        ctx["shortcuts"] = [
            {"label": "Ir para Estrutura", "icon": "bi-diagram-3", "link_name": "core:admin_arvore"},
            {"label": "Ir para Perfis", "icon": "bi-person-badge", "link_name": "core:perfis"},
        ]
        return ctx
