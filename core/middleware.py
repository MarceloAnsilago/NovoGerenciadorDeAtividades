# core/middleware.py
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
                if profile.first_login and request.path != reverse('primeiro_acesso'):
                    return redirect('primeiro_acesso')
            except UserProfile.DoesNotExist:
                pass  # Se não tiver perfil, ignora
        return self.get_response(request)
