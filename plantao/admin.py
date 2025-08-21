from django.contrib import admin
from .models import Plantao, Semana, SemanaServidor

class SemanaServidorInline(admin.TabularInline):
    model = SemanaServidor
    extra = 0

class SemanaInline(admin.StackedInline):
    model = Semana
    extra = 0

@admin.register(Plantao)
class PlantaoAdmin(admin.ModelAdmin):
    list_display = ("nome", "inicio", "fim", "criado_por", "criado_em")
    inlines = [SemanaInline]

@admin.register(Semana)
class SemanaAdmin(admin.ModelAdmin):
    list_display = ("plantao", "inicio", "fim", "ordem")
    inlines = [SemanaServidorInline]

@admin.register(SemanaServidor)
class SemanaServidorAdmin(admin.ModelAdmin):
    list_display = ("semana", "servidor", "ordem", "telefone_snapshot")
