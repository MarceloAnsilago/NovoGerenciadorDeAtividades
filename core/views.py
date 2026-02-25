from collections import defaultdict
import json
import calendar
from datetime import date
from urllib.parse import urlencode

# core/views.py

from django.apps import apps
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
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from django.views.generic import TemplateView
from django.urls import reverse
from django.conf import settings
from django.db import transaction
from django.db.models import deletion, Count, Q, Min, Max
from django.db.models.functions import TruncMonth

from .models import No, UserProfile  # No (Unidade) e UserProfile
from .models import No as Unidade
from .utils import gerar_senha_provisoria, get_unidade_scope_ids, get_unidade_atual
from .services.dashboard_queries import (
    get_dashboard_kpis,
    get_dashboard_activity_filters,
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


def _parse_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


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


def _collect_descendant_ids(root_id: int) -> list[int]:
    visited = {root_id}
    descendants = []
    frontier = [root_id]

    while frontier:
        child_ids = list(Unidade.objects.filter(parent_id__in=frontier).values_list("id", flat=True))
        frontier = [cid for cid in child_ids if cid not in visited]
        if not frontier:
            break
        visited.update(frontier)
        descendants.extend(frontier)

    return descendants


def _iter_unidade_fk_fields():
    for model in apps.get_models():
        for field in model._meta.get_fields():
            if not getattr(field, "is_relation", False):
                continue
            if not getattr(field, "many_to_one", False):
                continue
            if getattr(field, "auto_created", False):
                continue

            remote_field = getattr(field, "remote_field", None)
            remote_model = getattr(remote_field, "model", None)
            if remote_model is not Unidade:
                continue

            if model is Unidade and field.name == "parent":
                # relação de árvore é tratada separadamente (subunidades)
                continue

            yield model, field


def _build_unidade_dependency_rows(unidade_ids: list[int]) -> list[dict]:
    if not unidade_ids:
        return []

    rows = []
    for model, field in _iter_unidade_fk_fields():
        qs = model.objects.filter(**{f"{field.name}_id__in": unidade_ids})
        count = qs.count()
        if not count:
            continue

        action_code, action_label = _map_on_delete_action(field.remote_field.on_delete)
        model_label_lower = model._meta.label_lower
        rows.append(
            {
                "key": f"{model_label_lower}:{field.name}",
                "model_label": model_label_lower,
                "model": str(model._meta.verbose_name_plural),
                "model_singular": str(model._meta.verbose_name),
                "field": field.name,
                "count": count,
                "action": action_code,
                "action_label": str(action_label),
                "hint": DEPENDENCY_HINTS.get(model_label_lower),
            }
        )

    rows.sort(
        key=lambda item: (
            ACTION_PRIORITY.get(item["action"], 99),
            item["model"],
        )
    )
    return rows


def _dependency_action_totals(rows: list[dict]) -> dict:
    totals = defaultdict(int)
    for item in rows:
        totals[item["action"]] += item.get("count", 0)
    return dict(totals)


def _build_no_delete_preview(no: Unidade) -> dict:
    descendants_ids = _collect_descendant_ids(no.id)
    direct_children_count = Unidade.objects.filter(parent_id=no.id).count()

    direct_rows = _build_unidade_dependency_rows([no.id])
    descendants_rows = _build_unidade_dependency_rows(descendants_ids)
    subtree_rows = _build_unidade_dependency_rows([no.id] + descendants_ids)

    return {
        "node": {
            "id": no.id,
            "nome": no.nome,
            "parent_id": no.parent_id,
        },
        "parent": (
            {"id": no.parent_id, "nome": no.parent.nome}
            if no.parent_id and no.parent
            else None
        ),
        "direct_children_count": direct_children_count,
        "descendants_count": len(descendants_ids),
        "has_parent": bool(no.parent_id),
        "scopes": {
            "direct": {
                "rows": direct_rows,
                "totals": _dependency_action_totals(direct_rows),
            },
            "descendants": {
                "rows": descendants_rows,
                "totals": _dependency_action_totals(descendants_rows),
            },
            "subtree": {
                "rows": subtree_rows,
                "totals": _dependency_action_totals(subtree_rows),
            },
        },
    }


# ============ DASHBOARD ============

@login_required
def home(request):
    return render(request, "core/home.html")


def _parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_month_value(value):
    if not value:
        return None
    parts = str(value).split("-")
    if len(parts) != 2:
        return None
    year = _parse_int(parts[0])
    month = _parse_int(parts[1])
    if not year or not month or month < 1 or month > 12:
        return None
    return year, month


def _extract_month_bounds(months_by_year: dict) -> tuple[str | None, str | None]:
    pairs = []
    for year_key, months in months_by_year.items():
        year = _parse_int(year_key)
        if not year:
            continue
        for month in months or []:
            month_int = _parse_int(month)
            if not month_int:
                continue
            pairs.append((year, month_int))

    if not pairs:
        return None, None

    pairs.sort()
    min_year, min_month = pairs[0]
    max_year, max_month = pairs[-1]
    return f"{min_year:04d}-{min_month:02d}", f"{max_year:04d}-{max_month:02d}"


def _dashboard_period_range(start_value, end_value):
    start = _parse_month_value(start_value)
    end = _parse_month_value(end_value)
    if not start and not end:
        return None, None
    if not start:
        start = end
    if not end:
        end = start

    start_year, start_month = start
    end_year, end_month = end
    if (start_year, start_month) > (end_year, end_month):
        start_year, start_month, end_year, end_month = end_year, end_month, start_year, start_month

    start_date = date(start_year, start_month, 1)
    end_last_day = calendar.monthrange(end_year, end_month)[1]
    end_date = date(end_year, end_month, end_last_day)
    return start_date, end_date


def _month_value_from_date(value):
    if not value:
        return None
    return f"{value.year:04d}-{value.month:02d}"


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


@require_GET
@login_required
@user_passes_test(lambda u: u.is_staff)
def nos_dependencias(request, pk):
    no = get_object_or_404(Unidade.objects.select_related("parent"), pk=pk)
    preview = _build_no_delete_preview(no)
    return JsonResponse({"status": "ok", "preview": preview})


@require_POST
@login_required
@user_passes_test(lambda u: u.is_staff)
def nos_deletar(request, pk):
    no = get_object_or_404(Unidade.objects.select_related("parent"), pk=pk)

    payload = {}
    content_type = request.META.get("CONTENT_TYPE", "")
    if "application/json" in content_type.lower():
        try:
            payload = json.loads((request.body or b"{}").decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}
    if not payload:
        payload = request.POST

    confirm = _parse_bool(payload.get("confirm"))
    delete_descendants = _parse_bool(payload.get("delete_descendants"))
    reassign_blockers = _parse_bool(payload.get("reassign_blockers"))

    raw_delete_keys = payload.get("delete_keys", [])
    if isinstance(raw_delete_keys, str):
        delete_keys = {key.strip() for key in raw_delete_keys.split(",") if key.strip()}
    elif isinstance(raw_delete_keys, list):
        delete_keys = {str(key).strip() for key in raw_delete_keys if str(key).strip()}
    else:
        delete_keys = set()

    preview = _build_no_delete_preview(no)
    if not confirm:
        return JsonResponse(
            {
                "status": "confirm_required",
                "message": "Confirme a exclusao para continuar.",
                "preview": preview,
            },
            status=400,
        )

    descendants_ids = _collect_descendant_ids(no.id)
    affected_unit_ids = [no.id] + (descendants_ids if delete_descendants else [])
    scope_rows = _build_unidade_dependency_rows(affected_unit_ids)

    blockers = [row for row in scope_rows if row["action"] in {"protect", "restrict"}]
    cascades = [row for row in scope_rows if row["action"] == "cascade"]
    cascade_to_preserve = [row for row in cascades if row["key"] not in delete_keys]

    parent = no.parent

    if blockers and not reassign_blockers:
        return JsonResponse(
            {
                "status": "blocked",
                "message": "Existem vinculos bloqueadores. Marque a opcao de reatribuir bloqueios ou cancele.",
                "preview": preview,
                "scope_rows": scope_rows,
            },
            status=400,
        )

    if blockers and parent is None:
        return JsonResponse(
            {
                "status": "blocked",
                "message": "Nao e possivel excluir unidade raiz com vinculos bloqueadores sem unidade pai para reatribuir.",
                "preview": preview,
                "scope_rows": scope_rows,
            },
            status=400,
        )

    if cascade_to_preserve and parent is None:
        return JsonResponse(
            {
                "status": "blocked",
                "message": (
                    "Nao ha unidade pai para preservar os vinculos marcados como manter. "
                    "Marque-os para excluir ou cancele."
                ),
                "preview": preview,
                "scope_rows": scope_rows,
            },
            status=400,
        )

    field_map = {}
    for model, field in _iter_unidade_fk_fields():
        key = f"{model._meta.label_lower}:{field.name}"
        field_map[key] = (model, field)

    report = {
        "moved": [],
        "deleted": [],
        "moved_children": 0,
    }

    try:
        with transaction.atomic():
            for row in scope_rows:
                key = row["key"]
                mapping = field_map.get(key)
                if mapping is None:
                    continue
                model, field = mapping
                qs = model.objects.filter(**{f"{field.name}_id__in": affected_unit_ids})
                count = qs.count()
                if not count:
                    continue

                action = row["action"]
                if action in {"protect", "restrict"}:
                    if reassign_blockers:
                        updated = qs.update(**{field.name: parent})
                        if updated:
                            report["moved"].append({"model": row["model"], "count": updated})
                    continue

                if action == "cascade":
                    if key in delete_keys:
                        deleted_count, _ = qs.delete()
                        if deleted_count:
                            report["deleted"].append({"model": row["model"], "count": deleted_count})
                    else:
                        updated = qs.update(**{field.name: parent})
                        if updated:
                            report["moved"].append({"model": row["model"], "count": updated})
                    continue

            if not delete_descendants:
                moved_children = Unidade.objects.filter(parent_id=no.id).update(parent=parent)
                report["moved_children"] = moved_children

            no.delete()
    except ProtectedError as exc:
        return JsonResponse(
            {
                "status": "blocked",
                "message": "A exclusao foi bloqueada por registros protegidos.",
                "error": str(exc),
                "preview": _build_no_delete_preview(no),
            },
            status=400,
        )
    except Exception as exc:
        return JsonResponse(
            {
                "status": "error",
                "message": "Falha ao executar exclusao segura da unidade.",
                "error": str(exc),
            },
            status=500,
        )

    return JsonResponse(
        {
            "status": "ok",
            "message": "Unidade excluida com sucesso.",
            "report": report,
        }
    )


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
    unidade_scope = get_unidade_scope_ids(request)
    filters = get_dashboard_activity_filters(request.user, unidade_ids=unidade_scope)
    years = filters.get("years") or []
    months_by_year = filters.get("months_by_year") or {}
    min_month_value, max_month_value = _extract_month_bounds(months_by_year)
    start_param = request.GET.get("inicio") or request.GET.get("start")
    end_param = request.GET.get("fim") or request.GET.get("end")
    start_value = start_param if _parse_month_value(start_param) else min_month_value
    end_value = end_param if _parse_month_value(end_param) else max_month_value

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
        "dashboard_month_min": min_month_value,
        "dashboard_month_max": max_month_value,
        "dashboard_month_start": start_value,
        "dashboard_month_end": end_value,
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
    start_value = request.GET.get("inicio") or request.GET.get("start")
    end_value = request.GET.get("fim") or request.GET.get("end")
    start_date, end_date = _dashboard_period_range(start_value, end_value)
    data = get_atividades_por_area(
        request.user,
        unidade_ids=unidade_scope,
        start_date=start_date,
        end_date=end_date,
    )
    return JsonResponse(data)


@login_required
@require_GET
def dashboard_progresso_mensal(request):
    unidade_scope = get_unidade_scope_ids(request)
    start_value = request.GET.get("inicio") or request.GET.get("start")
    end_value = request.GET.get("fim") or request.GET.get("end")
    start_date, end_date = _dashboard_period_range(start_value, end_value)
    data = get_progresso_mensal(
        request.user,
        unidade_ids=unidade_scope,
        start_date=start_date,
        end_date=end_date,
    )
    return JsonResponse(data)


@login_required
@require_GET
def dashboard_programacoes_status_mensal(request):
    unidade_scope = get_unidade_scope_ids(request)
    start_value = request.GET.get("inicio") or request.GET.get("start")
    end_value = request.GET.get("fim") or request.GET.get("end")
    start_date, end_date = _dashboard_period_range(start_value, end_value)
    data = get_programacoes_status_mensal(
        request.user,
        unidade_ids=unidade_scope,
        start_date=start_date,
        end_date=end_date,
    )
    return JsonResponse(data)


@login_required
@require_GET
def dashboard_plantao_heatmap(request):
    unidade_scope = get_unidade_scope_ids(request)
    start_value = request.GET.get("inicio") or request.GET.get("start")
    end_value = request.GET.get("fim") or request.GET.get("end")
    start_date, end_date = _dashboard_period_range(start_value, end_value)
    data = get_plantao_heatmap(
        request.user,
        unidade_ids=unidade_scope,
        start_date=start_date,
        end_date=end_date,
    )
    return JsonResponse(data)


@login_required
@require_GET
def dashboard_uso_veiculos(request):
    unidade_scope = get_unidade_scope_ids(request)
    start_value = request.GET.get("inicio") or request.GET.get("start")
    end_value = request.GET.get("fim") or request.GET.get("end")
    start_date, end_date = _dashboard_period_range(start_value, end_value)
    data = get_uso_veiculos(
        request.user,
        unidade_ids=unidade_scope,
        start_date=start_date,
        end_date=end_date,
    )
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
    start_value = request.GET.get("inicio") or request.GET.get("start")
    end_value = request.GET.get("fim") or request.GET.get("end")
    start_date, end_date = _dashboard_period_range(start_value, end_value)
    data = get_top_servidores(
        request.user,
        unidade_ids=unidade_scope,
        limit=limit,
        start_date=start_date,
        end_date=end_date,
    )
    return JsonResponse(data)


@login_required
@require_GET
def dashboard_servidor_view(request, servidor_id):
    from programar.models import ProgramacaoItemServidor
    from servidores.models import Servidor

    unidade_scope = get_unidade_scope_ids(request)

    servidor_qs = Servidor.objects.select_related("unidade", "cargo")
    if unidade_scope is not None:
        if unidade_scope:
            servidor_qs = servidor_qs.filter(unidade_id__in=unidade_scope)
        else:
            servidor_qs = servidor_qs.none()

    servidor = get_object_or_404(servidor_qs, pk=servidor_id)

    base_qs = ProgramacaoItemServidor.objects.select_related(
        "item__programacao__unidade",
        "item__meta__atividade__area",
        "item__veiculo",
        "servidor__unidade",
        "servidor__cargo",
    ).filter(servidor_id=servidor.id)

    if unidade_scope is not None:
        base_qs = base_qs.filter(item__programacao__unidade_id__in=unidade_scope)

    bounds = base_qs.exclude(item__programacao__data__isnull=True).aggregate(
        min_data=Min("item__programacao__data"),
        max_data=Max("item__programacao__data"),
    )
    min_month_value = _month_value_from_date(bounds.get("min_data"))
    max_month_value = _month_value_from_date(bounds.get("max_data"))

    start_param = request.GET.get("inicio") or request.GET.get("start")
    end_param = request.GET.get("fim") or request.GET.get("end")
    start_value = start_param if _parse_month_value(start_param) else min_month_value
    end_value = end_param if _parse_month_value(end_param) else max_month_value

    start_date, end_date = _dashboard_period_range(start_value, end_value)

    period_qs = base_qs
    if start_date and end_date:
        period_qs = period_qs.filter(item__programacao__data__range=(start_date, end_date))

    total_alocacoes = period_qs.count()
    concluidas = period_qs.filter(item__concluido=True).count()
    pendentes = max(total_alocacoes - concluidas, 0)
    taxa_conclusao = round((concluidas / total_alocacoes) * 100, 2) if total_alocacoes else 0.0

    metas_distintas = period_qs.values("item__meta_id").distinct().count()
    atividades_distintas = (
        period_qs.exclude(item__meta__atividade_id__isnull=True)
        .values("item__meta__atividade_id")
        .distinct()
        .count()
    )
    dias_programados = period_qs.values("item__programacao__data").distinct().count()
    unidades_atuacao = period_qs.values("item__programacao__unidade_id").distinct().count()
    veiculos_usados = period_qs.exclude(item__veiculo_id__isnull=True).values("item__veiculo_id").distinct().count()
    com_observacao = (
        period_qs.exclude(item__observacao__isnull=True)
        .exclude(item__observacao__exact="")
        .count()
    )

    extremos = period_qs.aggregate(
        primeira_data=Min("item__programacao__data"),
        ultima_data=Max("item__programacao__data"),
    )

    meta_expediente_id = getattr(settings, "META_EXPEDIENTE_ID", None)
    try:
        meta_expediente_id = int(meta_expediente_id) if meta_expediente_id is not None else None
    except (TypeError, ValueError):
        meta_expediente_id = None

    expediente_total = None
    campo_total = None
    if meta_expediente_id:
        expediente_total = period_qs.filter(item__meta_id=meta_expediente_id).count()
        campo_total = max(total_alocacoes - expediente_total, 0)

    area_rows = []
    area_qs = (
        period_qs.values("item__meta__atividade__area__nome")
        .annotate(total=Count("id"))
        .order_by("-total", "item__meta__atividade__area__nome")
    )
    for row in area_qs:
        area_rows.append(
            {
                "nome": row.get("item__meta__atividade__area__nome") or "Sem area",
                "total": int(row.get("total") or 0),
            }
        )

    unidade_rows = []
    unidade_qs = (
        period_qs.values("item__programacao__unidade__nome")
        .annotate(total=Count("id"))
        .order_by("-total", "item__programacao__unidade__nome")
    )
    for row in unidade_qs:
        unidade_rows.append(
            {
                "nome": row.get("item__programacao__unidade__nome") or "Sem unidade",
                "total": int(row.get("total") or 0),
            }
        )

    veiculo_rows = []
    veiculo_qs = (
        period_qs.exclude(item__veiculo__placa__isnull=True)
        .exclude(item__veiculo__placa__exact="")
        .values("item__veiculo__placa")
        .annotate(total=Count("id"))
        .order_by("-total", "item__veiculo__placa")[:15]
    )
    for row in veiculo_qs:
        veiculo_rows.append(
            {
                "placa": row.get("item__veiculo__placa"),
                "total": int(row.get("total") or 0),
            }
        )

    atividade_rows = []
    atividade_qs = (
        period_qs.values(
            "item__meta__atividade__titulo",
            "item__meta__titulo",
            "item__meta__atividade__area__nome",
        )
        .annotate(
            total=Count("id"),
            concluidas=Count("id", filter=Q(item__concluido=True)),
            pendentes=Count("id", filter=Q(item__concluido=False)),
            ultima_data=Max("item__programacao__data"),
        )
        .order_by("-total", "item__meta__atividade__titulo", "item__meta__titulo")[:20]
    )
    for row in atividade_qs:
        atividade_rows.append(
            {
                "atividade": row.get("item__meta__atividade__titulo") or row.get("item__meta__titulo") or "Sem titulo",
                "area": row.get("item__meta__atividade__area__nome") or "Sem area",
                "total": int(row.get("total") or 0),
                "concluidas": int(row.get("concluidas") or 0),
                "pendentes": int(row.get("pendentes") or 0),
                "ultima_data": row.get("ultima_data"),
            }
        )

    meta_rows = []
    meta_qs = (
        period_qs.values(
            "item__meta_id",
            "item__meta__titulo",
            "item__meta__atividade__titulo",
            "item__meta__encerrada",
        )
        .annotate(
            total=Count("id"),
            concluidas=Count("id", filter=Q(item__concluido=True)),
            pendentes=Count("id", filter=Q(item__concluido=False)),
            ultima_data=Max("item__programacao__data"),
        )
        .order_by("-total", "item__meta__titulo")[:20]
    )
    for row in meta_qs:
        meta_rows.append(
            {
                "meta_id": row.get("item__meta_id"),
                "titulo": row.get("item__meta__atividade__titulo") or row.get("item__meta__titulo") or "Sem titulo",
                "encerrada": bool(row.get("item__meta__encerrada")),
                "total": int(row.get("total") or 0),
                "concluidas": int(row.get("concluidas") or 0),
                "pendentes": int(row.get("pendentes") or 0),
                "ultima_data": row.get("ultima_data"),
            }
        )

    mensal_rows = []
    mensal_qs = (
        period_qs.annotate(mes=TruncMonth("item__programacao__data"))
        .values("mes")
        .annotate(
            total=Count("id"),
            concluidas=Count("id", filter=Q(item__concluido=True)),
            pendentes=Count("id", filter=Q(item__concluido=False)),
        )
        .order_by("mes")
    )
    for row in mensal_qs:
        mes = row.get("mes")
        mes_label = mes.strftime("%m/%Y") if mes else "-"
        mensal_rows.append(
            {
                "mes": mes_label,
                "total": int(row.get("total") or 0),
                "concluidas": int(row.get("concluidas") or 0),
                "pendentes": int(row.get("pendentes") or 0),
            }
        )

    recentes_rows = []
    recentes_qs = period_qs.order_by("-item__programacao__data", "-item_id")[:120]
    for link in recentes_qs:
        item = link.item
        meta = item.meta
        atividade = getattr(meta, "atividade", None)
        area = getattr(atividade, "area", None)
        programacao = item.programacao
        unidade = getattr(programacao, "unidade", None)
        veiculo = item.veiculo
        recentes_rows.append(
            {
                "data": getattr(programacao, "data", None),
                "unidade": getattr(unidade, "nome", "Sem unidade"),
                "meta": getattr(meta, "display_titulo", None) or getattr(meta, "titulo", "Sem titulo"),
                "atividade": getattr(atividade, "titulo", "") or "-",
                "area": getattr(area, "nome", "") or "-",
                "concluido": bool(item.concluido),
                "concluido_em": item.concluido_em,
                "veiculo": getattr(veiculo, "placa", "") or "-",
                "observacao": (item.observacao or "").strip(),
            }
        )

    period_label = "Todo o historico"
    if start_date and end_date:
        period_label = f"{start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}"

    params = {}
    if start_value:
        params["inicio"] = start_value
    if end_value:
        params["fim"] = end_value
    period_query = urlencode(params)

    dashboard_return_url = reverse("core:dashboard")
    if period_query:
        dashboard_return_url = f"{dashboard_return_url}?{period_query}"

    context = {
        "servidor": servidor,
        "period_label": period_label,
        "dashboard_month_min": min_month_value,
        "dashboard_month_max": max_month_value,
        "dashboard_month_start": start_value,
        "dashboard_month_end": end_value,
        "dashboard_return_url": dashboard_return_url,
        "kpis": {
            "total_alocacoes": total_alocacoes,
            "concluidas": concluidas,
            "pendentes": pendentes,
            "taxa_conclusao": taxa_conclusao,
            "metas_distintas": metas_distintas,
            "atividades_distintas": atividades_distintas,
            "dias_programados": dias_programados,
            "unidades_atuacao": unidades_atuacao,
            "veiculos_usados": veiculos_usados,
            "com_observacao": com_observacao,
            "primeira_data": extremos.get("primeira_data"),
            "ultima_data": extremos.get("ultima_data"),
            "expediente_total": expediente_total,
            "campo_total": campo_total,
        },
        "area_rows": area_rows,
        "unidade_rows": unidade_rows,
        "veiculo_rows": veiculo_rows,
        "atividade_rows": atividade_rows,
        "meta_rows": meta_rows,
        "mensal_rows": mensal_rows,
        "recentes_rows": recentes_rows,
    }
    return render(request, "core/dashboard_servidor.html", context)
