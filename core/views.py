from collections import defaultdict

# core/views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.http import require_POST, require_GET
from django.contrib.auth.decorators import login_required, user_passes_test, permission_required
from django.contrib.auth import authenticate, logout, login as auth_login, get_user_model
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.utils.http import url_has_allowed_host_and_scheme
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.views.generic import TemplateView
from django.urls import reverse
from django.db import transaction
from django.db.models import deletion

from .models import No, UserProfile  # No (Unidade) e UserProfile
from .models import No as Unidade
from .utils import gerar_senha_provisoria, get_unidade_scope_ids, get_unidade_atual
from .services.dashboard_queries import (
    get_dashboard_kpis,
    get_metas_por_unidade,
    get_atividades_por_area,
    get_progresso_mensal,
    get_programacoes_status_mensal,
    get_plantao_heatmap,
    get_uso_veiculos,
    get_top_servidores,
)
# from .forms import UserProfileForm  # removido: não utilizado

# Inicializa o modelo de usuário
User = get_user_model()

CASCADE = deletion.CASCADE
PROTECT = deletion.PROTECT
SET_NULL = deletion.SET_NULL
SET_DEFAULT = deletion.SET_DEFAULT
DO_NOTHING = deletion.DO_NOTHING
ProtectedError = deletion.ProtectedError
RESTRICT = getattr(deletion, "RESTRICT", None)

ON_DELETE_ACTIONS = {
    CASCADE: ("cascade", "Será removido automaticamente junto com o usuário."),
    PROTECT: ("protect", "Bloqueia a exclusão enquanto esse registro existir."),
    SET_NULL: ("set_null", "O vínculo será limpo; o registro permanece no sistema."),
    SET_DEFAULT: ("set_default", "O vínculo receberá o valor padrão configurado."),
    DO_NOTHING: ("do_nothing", "Nenhuma ação automática será realizada."),
}
if RESTRICT:
    ON_DELETE_ACTIONS[RESTRICT] = ("restrict", "Bloqueia a exclusão (restrito).")

ACTION_PRIORITY = {
    "protect": 0,
    "restrict": 0,
    "cascade": 1,
    "set_null": 2,
    "set_default": 3,
    "detach": 4,
    "do_nothing": 5,
    "unknown": 6,
}

DEPENDENCY_HINTS = {
    "metas.meta": "Acesse Metas ► Metas da Unidade para reatribuir o criador ou encerrar a meta.",
    "metas.metaalocacao": "Revise as alocações em Metas ► Atribuir Meta para redistribuir a responsabilidade.",
    "metas.progessometa": "Revise os lançamentos em Metas ► Atribuir / Progresso antes de excluir.",
    "atividades.atividade": "Abra Metas ► Atividades para transferir ou remover a atividade.",
    "programar.programacaoitem": "Confira Programar ► Programações para desassociar esta meta/atividade.",
    "descanso.descanso": "Vá em Descanso ► Servidores para remover ou reatribuir o registro.",
    "plantao.plantao": "Confira Plantão ► Lista para ajustar o responsável pelo plantão.",
}


def _map_on_delete_action(on_delete):
    if on_delete in ON_DELETE_ACTIONS:
        return ON_DELETE_ACTIONS[on_delete]
    if hasattr(on_delete, "__name__"):
        name = on_delete.__name__
        return (name.lower(), f"Ação '{name}' aplicada aos registros relacionados.")
    return ("unknown", "Ação personalizada definida no modelo relacionado.")


def _build_user_dependency_summary(user):
    summary = []
    totals = defaultdict(int)
    blockers = []

    for rel in user._meta.get_fields():
        if not getattr(rel, "is_relation", False):
            continue
        if not getattr(rel, "auto_created", False):
            continue
        if not hasattr(rel, "get_accessor_name"):
            continue

        accessor_name = rel.get_accessor_name()
        related_model = getattr(rel, "related_model", None)
        if related_model is None:
            continue

        if getattr(rel, "many_to_many", False):
            manager = getattr(user, accessor_name, None)
            if manager is None:
                continue
            count = manager.count()
            if not count:
                continue
            samples = [str(obj) for obj in manager.all()[:3]]
            item = {
                "relation": accessor_name,
                "model": related_model._meta.verbose_name_plural,
                "model_singular": related_model._meta.verbose_name,
                "model_label": f"{related_model._meta.app_label}.{related_model._meta.model_name}",
                "action": "detach",
                "action_label": "As ligações serão removidas, mas os registros permanecerão disponíveis.",
                "count": count,
                "samples": samples,
            }
            summary.append(item)
            totals["detach"] += count
            continue

        on_delete = getattr(rel, "on_delete", None)
        if on_delete is None and hasattr(rel, "field") and rel.field.remote_field:
            on_delete = rel.field.remote_field.on_delete

        action_code, action_label = _map_on_delete_action(on_delete)

        if rel.one_to_one:
            try:
                related_object = getattr(user, accessor_name)
            except related_model.DoesNotExist:
                continue
            related_objects = [related_object]
            count = 1
        else:
            manager = getattr(user, accessor_name, None)
            if manager is None:
                continue
            qs = manager.all()
            count = qs.count()
            if not count:
                continue
            related_objects = list(qs[:3])

        item = {
            "relation": accessor_name,
            "model": related_model._meta.verbose_name_plural,
            "model_singular": related_model._meta.verbose_name,
            "model_label": f"{related_model._meta.app_label}.{related_model._meta.model_name}",
            "action": action_code,
            "action_label": action_label,
            "count": count,
            "samples": [str(obj) for obj in related_objects],
            "hint": DEPENDENCY_HINTS.get(f"{related_model._meta.app_label}.{related_model._meta.model_name}"),
        }
        summary.append(item)
        totals[action_code] += count
        if action_code in {"protect", "restrict"}:
            blockers.append(item)

    summary.sort(
        key=lambda item: (
            ACTION_PRIORITY.get(item["action"], 99),
            item["model"],
        )
    )

    return summary, dict(totals), blockers


def _force_cleanup_user_dependencies(user):
    """
    Remove ou apaga dependências bloqueadoras (on_delete=PROTECT/RESTRICT) antes da exclusão.
    Retorna um relatório com as operações executadas.
    """
    report = {"deleted": [], "detached": [], "errors": []}

    for rel in user._meta.get_fields():
        if not getattr(rel, "is_relation", False):
            continue
        if not getattr(rel, "auto_created", False):
            continue
        if not hasattr(rel, "get_accessor_name"):
            continue

        accessor_name = rel.get_accessor_name()
        related_model = getattr(rel, "related_model", None)
        if related_model is None:
            continue

        verbose_name = related_model._meta.verbose_name_plural

        if getattr(rel, "many_to_many", False):
            manager = getattr(user, accessor_name, None)
            if manager is None:
                continue
            count = manager.count()
            if not count:
                continue
            try:
                manager.clear()
                report["detached"].append({"model": verbose_name, "count": count})
            except Exception as exc:
                report["errors"].append({"model": verbose_name, "error": str(exc)})
            continue

        on_delete = getattr(rel, "on_delete", None)
        if on_delete is None and hasattr(rel, "field") and rel.field.remote_field:
            on_delete = rel.field.remote_field.on_delete

        action_code, _ = _map_on_delete_action(on_delete)
        if action_code not in {"protect", "restrict"}:
            continue

        try:
            if rel.one_to_one:
                try:
                    related_object = getattr(user, accessor_name)
                except related_model.DoesNotExist:
                    continue
                queryset = related_model.objects.filter(pk=related_object.pk)
            else:
                manager = getattr(user, accessor_name, None)
                if manager is None:
                    continue
                queryset = manager.all()

            deleted_count, _deleted_map = queryset.delete()
            if deleted_count:
                report["deleted"].append({"model": verbose_name, "count": deleted_count})
        except ProtectedError as exc:
            report["errors"].append({"model": verbose_name, "error": str(exc)})
        except Exception as exc:
            report["errors"].append({"model": verbose_name, "error": str(exc)})

    return report


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
def perfil_dependencias(request, user_id):
    if not (
        request.user.is_superuser
        or request.user.has_perm("auth.delete_user")
        or request.user.has_perm("core.delete_userprofile")
        or request.user.has_perm("core.add_userprofile")
    ):
        return JsonResponse(
            {
                "status": "forbidden",
                "message": "Você não tem permissão para revisar ou excluir este perfil.",
            },
            status=403,
        )

    user = get_object_or_404(User, id=user_id)
    summary, totals, blockers = _build_user_dependency_summary(user)

    return JsonResponse({
        "status": "ok",
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
        },
        "summary": summary,
        "totals": totals,
        "can_delete": len(blockers) == 0,
    })


@login_required
@permission_required('core.add_userprofile', raise_exception=True)
def criar_perfil(request):
    if request.method != "POST":
        return JsonResponse({"status": "erro", "erro": "Método não permitido."}, status=405)

    try:
        username = request.POST.get("username")
        email = request.POST.get("email")
        raw_is_staff = request.POST.get("is_staff")
        is_staff = False
        if raw_is_staff is not None:
            is_staff = str(raw_is_staff).strip().lower() in {"1", "true", "on", "yes"}
        unidade_id = request.POST.get("unidade_id")

        if not (username and email and unidade_id):
            return JsonResponse({"status": "erro", "erro": "Dados incompletos."}, status=400)

        if User.objects.filter(username=username).exists():
            return JsonResponse({"status": "erro", "erro": "Já existe um usuário com esse nome."}, status=400)

        # Gera senha provisória
        senha_provisoria = gerar_senha_provisoria(8)

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
@permission_required('auth.delete_user', raise_exception=True)
def excluir_perfil(request, user_id):
    user = get_object_or_404(User, id=user_id)

    force_requested = request.POST.get("force") in {"1", "true", "yes"}
    cleanup_report = None

    summary, totals, blockers = _build_user_dependency_summary(user)

    if force_requested and blockers:
        cleanup_report = _force_cleanup_user_dependencies(user)
        summary, totals, blockers = _build_user_dependency_summary(user)

    if blockers:
        response_data = {
            "status": "bloqueado",
            "message": "Nao e possivel excluir o perfil enquanto existirem registros protegidos vinculados a este usuario.",
            "summary": summary,
            "totals": totals,
            "force_available": True,
        }
        if cleanup_report:
            response_data["cleanup"] = cleanup_report
        if force_requested:
            response_data["force_used"] = True
        return JsonResponse(response_data, status=400)

    if request.POST.get("confirm") not in {"1", "true", "yes"}:
        response_data = {
            "status": "confirm_required",
            "message": "Confirme a exclusao enviando o parametro confirm=1.",
            "summary": summary,
            "totals": totals,
            "force_available": True,
        }
        if cleanup_report:
            response_data["cleanup"] = cleanup_report
        if force_requested:
            response_data["force_used"] = True
        return JsonResponse(response_data, status=400)

    try:
        with transaction.atomic():
            user.delete()
        response_data = {"status": "excluido"}
        if cleanup_report:
            response_data["cleanup"] = cleanup_report
        if force_requested:
            response_data["force_used"] = True
        return JsonResponse(response_data)
    except ProtectedError:
        summary, totals, blockers = _build_user_dependency_summary(user)
        response_data = {
            "status": "bloqueado",
            "message": "A exclusao foi bloqueada porque ainda existem registros protegidos.",
            "summary": summary,
            "totals": totals,
            "force_available": True,
        }
        if cleanup_report:
            response_data["cleanup"] = cleanup_report
        if force_requested:
            response_data["force_used"] = True
        return JsonResponse(response_data, status=400)
    except Exception as exc:
        response_data = {"status": "erro", "erro": str(exc)}
        if cleanup_report:
            response_data["cleanup"] = cleanup_report
        if force_requested:
            response_data["force_used"] = True
        return JsonResponse(response_data, status=500)


@require_POST
@login_required
@permission_required('core.change_userprofile', raise_exception=True)
def redefinir_senha(request, user_id):
    user = get_object_or_404(User, pk=user_id)

    try:
        profile = user.userprofile
    except UserProfile.DoesNotExist:
        return JsonResponse({"status": "erro", "erro": "Perfil não encontrado."}, status=404)

    nova_senha = gerar_senha_provisoria(8)
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

def primeiro_acesso_token_view(request):
    context = {}
    if request.method == 'POST':
        username_input = (request.POST.get('username') or '').strip()
        token = (request.POST.get('token') or '').strip()
        context['username'] = username_input
        context['token'] = token
        if not username_input or not token:
            context['erro'] = "Token invalido ou ja utilizado."
            return render(request, 'core/primeiro_acesso_verificar.html', context)
        try:
            user = User.objects.get(username__iexact=username_input)
        except User.DoesNotExist:
            context['erro'] = "Usuario nao encontrado."
            return render(request, 'core/primeiro_acesso_verificar.html', context)
        try:
            profile = user.userprofile
        except UserProfile.DoesNotExist:
            context['erro'] = "Usuario nao encontrado."
            return render(request, 'core/primeiro_acesso_verificar.html', context)
        if profile.senha_provisoria == token and not profile.ativado:
            request.session['troca_user_id'] = user.id
            return redirect('core:trocar_senha_primeiro_acesso')
        context['erro'] = "Token invalido ou ja utilizado."
    return render(request, 'core/primeiro_acesso_verificar.html', context)


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
        username_input = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""
        if not username_input or not password:
            messages.error(request, "Usuario ou senha invalidos.")
            return render(request, "core/login.html")
        user = authenticate(request, username=username_input, password=password)
        if user is not None:
            auth_login(request, user)
            return redirect("core:dashboard")
        try:
            user_obj = User.objects.get(username__iexact=username_input)
        except User.DoesNotExist:
            messages.error(request, "Usuario ou senha invalidos.")
            return render(request, "core/login.html")
        if user_obj.username != username_input:
            user = authenticate(request, username=user_obj.username, password=password)
            if user is not None:
                auth_login(request, user)
                return redirect("core:dashboard")
        try:
            profile = user_obj.userprofile
        except UserProfile.DoesNotExist:
            messages.error(request, "Usuario ou senha invalidos.")
            return render(request, "core/login.html")
        if profile.senha_provisoria == password and not profile.ativado:
            request.session['troca_user_id'] = user_obj.id
            return redirect('core:trocar_senha_primeiro_acesso')
        messages.error(request, "Usuario ou senha invalidos.")
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


class AdminDashboardView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    template_name = "core/admin/dashboard.html"

    def test_func(self):
        user = self.request.user
        return user.is_superuser or user.is_staff

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            raise PermissionDenied
        return super().handle_no_permission()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        total_usuarios = User.objects.count()
        total_perfis = Group.objects.count()
        total_nos = No.objects.count()

        ctx["metrics"] = [
            {
                "label": "Usuarios",
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


@login_required
def dashboard_view(request):
    unidade = get_unidade_atual(request)
    hierarchy_summary = None

    if unidade:
        def collect_ids(root_id: int) -> list[int]:
            collected = {root_id}
            frontier = [root_id]
            while frontier:
                child_ids = list(No.objects.filter(parent_id__in=frontier).values_list("id", flat=True))
                child_ids = [cid for cid in child_ids if cid not in collected]
                if not child_ids:
                    break
                collected.update(child_ids)
                frontier = child_ids
            return list(collected)

        current_metrics = get_dashboard_kpis(request.user, unidade_ids=[unidade.id])

        children_rows = []
        all_children_ids: set[int] = set()
        for child in unidade.filhos.order_by("nome"):
            child_branch_ids = collect_ids(child.id)
            all_children_ids.update(child_branch_ids)
            children_rows.append(
                {
                    "id": child.id,
                    "nome": child.nome,
                    "metrics": get_dashboard_kpis(request.user, unidade_ids=child_branch_ids),
                }
            )

        aggregate_ids = collect_ids(unidade.id)
        aggregate_metrics = get_dashboard_kpis(request.user, unidade_ids=aggregate_ids)
        children_aggregate = None
        if all_children_ids:
            children_ids_list = sorted(all_children_ids)
            children_aggregate = get_dashboard_kpis(request.user, unidade_ids=children_ids_list)

        hierarchy_summary = {
            "current": {
                "id": unidade.id,
                "nome": unidade.nome,
                "metrics": current_metrics,
            },
            "children": children_rows,
            "children_metrics": children_aggregate,
            "aggregate": {
                "metrics": aggregate_metrics,
                "label": "Total (unidade atual + descendentes)",
            },
        }

    context = {
        "hierarchy_summary": hierarchy_summary,
    }
    return render(request, "core/dashboard.html", context)


@login_required
@require_GET
def dashboard_kpis(request):
    unidade_scope = get_unidade_scope_ids(request)
    data = get_dashboard_kpis(request.user, unidade_ids=unidade_scope)
    return JsonResponse(data)


@login_required
@require_GET
def dashboard_metas_por_unidade(request):
    unidade_scope = get_unidade_scope_ids(request)
    data = get_metas_por_unidade(request.user, unidade_ids=unidade_scope)
    return JsonResponse(data)


@login_required
@require_GET
def dashboard_atividades_por_area(request):
    unidade_scope = get_unidade_scope_ids(request)
    data = get_atividades_por_area(request.user, unidade_ids=unidade_scope)
    return JsonResponse(data)


@login_required
@require_GET
def dashboard_progresso_mensal(request):
    unidade_scope = get_unidade_scope_ids(request)
    data = get_progresso_mensal(request.user, unidade_ids=unidade_scope)
    return JsonResponse(data)


@login_required
@require_GET
def dashboard_programacoes_status_mensal(request):
    unidade_scope = get_unidade_scope_ids(request)
    data = get_programacoes_status_mensal(request.user, unidade_ids=unidade_scope)
    return JsonResponse(data)


@login_required
@require_GET
def dashboard_plantao_heatmap(request):
    unidade_scope = get_unidade_scope_ids(request)
    data = get_plantao_heatmap(request.user, unidade_ids=unidade_scope)
    return JsonResponse(data)


@login_required
@require_GET
def dashboard_uso_veiculos(request):
    unidade_scope = get_unidade_scope_ids(request)
    data = get_uso_veiculos(request.user, unidade_ids=unidade_scope)
    return JsonResponse(data)


@login_required
@require_GET
def dashboard_top_servidores(request):
    try:
        limit = int(request.GET.get("limit", 50))
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(limit, 200))
    unidade_scope = get_unidade_scope_ids(request)
    data = get_top_servidores(request.user, unidade_ids=unidade_scope, limit=limit)
    return JsonResponse(data)
