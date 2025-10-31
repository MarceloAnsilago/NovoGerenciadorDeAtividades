# core/middleware.py
from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse

from .models import UserProfile


class FirstLoginMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            try:
                profile = request.user.userprofile
            except UserProfile.DoesNotExist:
                return self.get_response(request)  # Usuário sem perfil: ignora

            # Usuários que ainda não ativaram devem concluir o primeiro acesso
            if not profile.ativado and profile.senha_provisoria:
                allowed_paths = {
                    reverse("core:primeiro_acesso_token"),
                    reverse("core:trocar_senha_primeiro_acesso"),
                    reverse("core:logout"),
                }
                path = request.path
                static_url = getattr(settings, "STATIC_URL", None)
                media_url = getattr(settings, "MEDIA_URL", None)

                if path not in allowed_paths:
                    if static_url and path.startswith(static_url):
                        return self.get_response(request)
                    if media_url and path.startswith(media_url):
                        return self.get_response(request)
                    return redirect("core:primeiro_acesso_token")

        return self.get_response(request)
