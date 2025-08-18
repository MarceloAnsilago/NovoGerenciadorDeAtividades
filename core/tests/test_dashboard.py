# core/views.py
from django.views.generic import TemplateView
from django.contrib.auth import get_user_model
from core.models import No  # <- aqui

class DashboardView(TemplateView):
    template_name = "core/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        User = get_user_model()
        ctx["metrics"] = [
            {"label": "Usuários", "value": User.objects.count(), "icon": "bi-people",
             "bg": "bg-primary-subtle", "fg": "text-primary", "link_name": "usuarios:list"},
            {"label": "Unidades / Estrutura", "value": No.objects.count(), "icon": "bi-diagram-3",
             "bg": "bg-warning-subtle", "fg": "text-warning", "link_name": "core:estrutura"},  # ajuste a rota
        ]
        return ctx
