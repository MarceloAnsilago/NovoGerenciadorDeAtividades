from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from .models import No, Policy, UserProfile


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    readonly_fields = ["senha_provisoria", "ativado"]
    fields = ["unidade", "senha_provisoria", "ativado"]


class CustomUserAdmin(BaseUserAdmin):
    inlines = (UserProfileInline,)
    readonly_fields = ["senha_provisoria_exibida"]

    def save_model(self, request, obj, form, change):
        if not obj.pk:  # novo usuário
            obj.set_unusable_password()  # usuário ainda não tem senha
        super().save_model(request, obj, form, change)

        if not change:
            default_unidade = No.objects.order_by("nome").first()
            if not default_unidade:
                messages.warning(
                    request,
                    "Cadastre ao menos uma unidade (Core > Nós) antes de gerar perfis e senhas provisórias.",
                )
                return

            profile, _ = UserProfile.objects.get_or_create(
                user=obj,
                defaults={"unidade": default_unidade},
            )
            if not profile.unidade:
                profile.unidade = default_unidade
                profile.save(update_fields=["unidade"])

            senha = profile.gerar_senha_provisoria()
            obj._senha_gerada = senha

    def senha_provisoria_exibida(self, obj):
        return getattr(obj, "_senha_gerada", "Salvo")

    senha_provisoria_exibida.short_description = "Senha Provisória"


admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)
admin.site.register(No)
admin.site.register(UserProfile)


@admin.register(Policy)
class PolicyAdmin(admin.ModelAdmin):
    list_display = ("user_profile", "can_read", "can_write", "scope")
    readonly_fields = ("user_profile",)
