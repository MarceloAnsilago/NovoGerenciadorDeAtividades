from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse


class ForcePasswordChangeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self._allowed = None

    def _allowed_paths(self):
        if self._allowed is None:
            allowed = set()

            def safe_reverse(name):
                try:
                    return reverse(name)
                except Exception:
                    return None

            # ✅ Usa o namespace 'core' corretamente
            for name in ("password_change", "password_change_done", "login", "logout"):
                url = safe_reverse(f"core:{name}")
                if url:
                    allowed.add(url)

            self._allowed = allowed

        return self._allowed

    def __call__(self, request):
        # Se o usuário não estiver autenticado, não precisa forçar troca de senha
        if not request.user.is_authenticated:
            return self.get_response(request)

        profile = getattr(request.user, "profile", None)

        # Verifica se o perfil exige troca de senha
        if profile and profile.must_change_password:
            path = request.path
            allowed = self._allowed_paths()

            is_allowed = (
                path in allowed or
                path.startswith("/admin/") or
                path.startswith(getattr(settings, "STATIC_URL", "/static/"))
            )

            # Evita redirecionar se já estiver na rota de troca de senha ou após ela
            if not is_allowed and path != reverse("core:password_change_done"):
                return redirect("core:password_change")

        # Caso contrário, segue o fluxo normal
        return self.get_response(request)

