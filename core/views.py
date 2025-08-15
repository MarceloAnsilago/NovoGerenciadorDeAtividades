# core/views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, logout, login as auth_login
from django.contrib.auth.forms import SetPasswordForm
import string, random

from .models import No, UserProfile
from .forms import UserProfileForm
# ============
# DASHBOARD
# ============

@login_required
def home(request):
    return render(request, "core/home.html")


# ============
# ÁRVORE (jsTree)
# ============

@user_passes_test(lambda u: u.is_staff)
def admin_arvore(request):
    tem_unidades = No.objects.exists()
    return render(request, "core/admin_arvore.html", {
        "tem_unidades": tem_unidades
    })

@login_required
def nos_list(request):
    dados = [no.to_jstree() for no in No.objects.all()]
    return JsonResponse(dados, safe=False)

@require_POST
@login_required
@user_passes_test(lambda u: u.is_staff)
def nos_criar(request):
    nome = request.POST.get('nome', 'Novo Nó')
    parent_id = request.POST.get('parent')
    parent = No.objects.filter(id=parent_id).first() if parent_id else None
    no = No.objects.create(nome=nome, parent=parent)
    return JsonResponse(no.to_jstree())

@require_POST
@login_required
@user_passes_test(lambda u: u.is_staff)
def nos_renomear(request, pk):
    no = get_object_or_404(No, pk=pk)
    novo_nome = request.POST.get('nome')
    if novo_nome:
        no.nome = novo_nome
        no.save()
        return JsonResponse({'status': 'ok'})
    return HttpResponseBadRequest('Nome inválido')

@require_POST
@login_required
@user_passes_test(lambda u: u.is_staff)
def nos_mover(request, pk):
    no = get_object_or_404(No, pk=pk)
    novo_parent_id = request.POST.get('parent')
    novo_parent = No.objects.filter(id=novo_parent_id).first() if novo_parent_id else None
    no.parent = novo_parent
    no.save()
    return JsonResponse({'status': 'ok'})

@require_POST
@login_required
@user_passes_test(lambda u: u.is_staff)
def nos_deletar(request, pk):
    no = get_object_or_404(No, pk=pk)
    no.delete()
    return JsonResponse({'status': 'ok'})


# ============
# PERFIS
# ============

@login_required
def perfis(request):
    return render(request, "core/perfis.html")

def gerar_senha_provisoria(tamanho=10):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=tamanho))

@csrf_exempt  # remova se seu frontend envia CSRF corretamente
@login_required
def criar_perfil(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        unidade_id = request.POST.get('unidade_id')
        is_admin = request.POST.get('is_admin') == 'on'

        if not (username and email and unidade_id):
            return JsonResponse({'erro': 'Campos obrigatórios faltando'}, status=400)

        if User.objects.filter(username=username).exists():
            return JsonResponse({'erro': 'Usuário já existe'}, status=400)

        senha_provisoria = gerar_senha_provisoria()

        # Criação do usuário
        user = User.objects.create_user(
            username=username,
            email=email,
        )
        user.is_staff = is_admin
        user.is_active = True
        user.set_unusable_password()  # Bloqueia login direto
        user.save()

        # Criação do UserProfile
        unidade = get_object_or_404(No, pk=unidade_id)
        profile = UserProfile.objects.create(
            user=user,
            unidade=unidade,
            senha_provisoria=senha_provisoria,
            ativado=False
        )

        # Retorna a senha provisória para o frontend (para exibir ao admin)
        return JsonResponse({
            'status': 'ok',
            'mensagem': f'Usuário criado. Senha provisória: {senha_provisoria}'
        })

    return HttpResponseBadRequest("Apenas requisições POST são permitidas.")

@login_required
def perfis(request):
    unidades = No.objects.prefetch_related('filhos', 'userprofile_set', 'userprofile_set__user')
    return render(request, "core/perfis.html", {"unidades": unidades})




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
            else:
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

            # Limpa sessão temporária
            del request.session['troca_user_id']

            # Faz login automático
            auth_login(request, user)
            messages.success(request, "Senha alterada com sucesso! Bem-vindo(a) ao sistema.")
            return redirect('core:dashboard')
        else:
            messages.error(request, "Erro ao alterar senha. Verifique os campos.")
    else:
        form = SetPasswordForm(user)

    return render(request, 'core/primeiro_acesso_trocar_senha.html', {'form': form})




# ============
# AUTENTICAÇÃO
# ============

from django.contrib.auth import authenticate, login
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.models import User
from .models import UserProfile

def login_view(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        # 1️⃣ Tentativa de login normal
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect("core:dashboard")

        # 2️⃣ Se não autenticou, tenta validar como senha provisória
        try:
            user_obj = User.objects.get(username=username)
            profile = user_obj.userprofile
        except (User.DoesNotExist, UserProfile.DoesNotExist):
            messages.error(request, "Usuário ou senha inválidos.")
            return render(request, "core/login.html")

        if profile.senha_provisoria == password and not profile.ativado:
            # Guarda ID do usuário para fluxo de troca de senha
            request.session['troca_user_id'] = user_obj.id
            return redirect('core:trocar_senha_primeiro_acesso')

        # 3️⃣ Se não for senha provisória válida nem senha normal
        messages.error(request, "Usuário ou senha inválidos.")
        return render(request, "core/login.html")

    return render(request, "core/login.html")

def logout_view(request):
    logout(request)
    messages.success(request, "Você saiu da sessão.")
    return redirect("core:login")
