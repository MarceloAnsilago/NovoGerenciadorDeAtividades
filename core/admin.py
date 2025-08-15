from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import UserProfile, No
from django.contrib import admin
from .models import Policy


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    readonly_fields = ['senha_provisoria', 'ativado']
    fields = ['unidade', 'senha_provisoria', 'ativado']

class CustomUserAdmin(BaseUserAdmin):
    inlines = (UserProfileInline,)
    readonly_fields = ['senha_provisoria_exibida']

    def save_model(self, request, obj, form, change):
        if not obj.pk:  # novo usuário
            obj.set_unusable_password()  # usuário ainda não tem senha
        super().save_model(request, obj, form, change)

        if not change:
            profile, _ = UserProfile.objects.get_or_create(user=obj, unidade=No.objects.first())  # Ajuste a lógica de unidade!
            senha = profile.gerar_senha_provisoria()
            obj._senha_gerada = senha

    def senha_provisoria_exibida(self, obj):
        return getattr(obj, '_senha_gerada', 'Salvo')
    senha_provisoria_exibida.short_description = 'Senha Provisória'

admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)
admin.site.register(No)
admin.site.register(UserProfile)


@admin.register(Policy)
class PolicyAdmin(admin.ModelAdmin):
    list_display = ('user_profile', 'can_read', 'can_write', 'scope')
    readonly_fields = ('user_profile',)