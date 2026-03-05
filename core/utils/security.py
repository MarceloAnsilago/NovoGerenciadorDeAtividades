from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.db.models import QuerySet
from django.utils.http import url_has_allowed_host_and_scheme


def safe_next_url(request, fallback: str) -> str:
    """
    Retorna uma URL local segura para redirecionamento.
    """
    candidate = (
        request.POST.get("next")
        or request.GET.get("next")
        or request.META.get("HTTP_REFERER")
        or ""
    ).strip()
    if candidate and url_has_allowed_host_and_scheme(candidate, allowed_hosts={request.get_host()}):
        return candidate
    return fallback


def get_unidade_atual(request):
    """
    Resolve unidade atual priorizando sessão e depois perfil do usuário.
    """
    ctx = request.session.get("contexto")
    if isinstance(ctx, dict) and ctx.get("tipo") == "unidade":
        uid = ctx.get("id") or ctx.get("unidade_id")
        if uid:
            from core.models import No

            return No.objects.filter(pk=uid).first()

    for session_key in ("contexto_atual", "unidade_id"):
        uid = request.session.get(session_key)
        if uid:
            try:
                from core.models import No

                return No.objects.filter(pk=int(uid)).first()
            except (TypeError, ValueError):
                continue

    user = getattr(request, "user", None)
    if user:
        for attr in ("userprofile", "profile", "perfil"):
            obj = getattr(user, attr, None)
            if obj and getattr(obj, "unidade_id", None):
                return getattr(obj, "unidade", None)
    return None


def get_unidade_atual_id(request):
    unidade = get_unidade_atual(request)
    return unidade.pk if unidade else None


def assert_unidade_scope(queryset: QuerySet, user, *, field: str = "unidade_id") -> QuerySet:
    """
    Restringe queryset pela unidade do usuário.
    """
    if getattr(user, "is_superuser", False):
        return queryset
    profile = getattr(user, "userprofile", None)
    unidade_id = getattr(profile, "unidade_id", None)
    if not unidade_id:
        raise PermissionDenied("Usuário sem unidade definida.")
    return queryset.filter(**{field: unidade_id})


def assert_unidade(obj, user, *, field: str = "unidade_id") -> None:
    """
    Valida se um objeto pertence a unidade do usuario (exceto superuser).
    """
    if getattr(user, "is_superuser", False):
        return
    profile = getattr(user, "userprofile", None)
    unidade_id = getattr(profile, "unidade_id", None)
    if not unidade_id:
        raise PermissionDenied("Usuario sem unidade definida.")
    if getattr(obj, field, None) != unidade_id:
        raise PermissionDenied("Objeto fora do escopo da unidade.")
