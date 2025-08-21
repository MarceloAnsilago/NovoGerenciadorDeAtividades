from django.contrib import admin
from .models import Plantao, Semana, SemanaServidor

class SemanaServidorInline(admin.TabularInline):
    model = SemanaServidor
    extra = 0

class SemanaInline(admin.StackedInline):
    model = Semana
    extra = 0

from django.contrib import admin
from .models import Plantao

@admin.register(Plantao)
class PlantaoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'inicio', 'fim', 'unidade', 'criado_por')
    list_filter = ('unidade',)
    search_fields = ('nome','observacao')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        # se o usuário tem profile com unidade (ajuste se sua app usa outro campo)
        unidade_id = getattr(request.user, "userprofile", None) and getattr(request.user.userprofile, "unidade_id", None)
        if unidade_id:
            return qs.filter(unidade_id=unidade_id)
        return qs.none()

@admin.register(Semana)
class SemanaAdmin(admin.ModelAdmin):
    list_display = ("plantao", "inicio", "fim", "ordem")
    inlines = [SemanaServidorInline]

@admin.register(SemanaServidor)
class SemanaServidorAdmin(admin.ModelAdmin):
    list_display = ("semana", "servidor", "ordem", "telefone_snapshot")
