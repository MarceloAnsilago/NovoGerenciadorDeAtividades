# controle_acesso/forms.py
from django import forms
from django.contrib.auth.models import Permission, User

class PermissoesUsuarioForm(forms.ModelForm):
    permissoes = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.all().select_related('content_type'),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Permissões"
    )

    class Meta:
        model = User
        fields = []  # não vamos editar campos do User aqui

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # ✅ Envie SEMPRE IDs no initial (evita comparar objeto no template)
        if self.instance and self.instance.pk:
            self.initial['permissoes'] = list(
                self.instance.user_permissions.values_list('id', flat=True)
            )

    def save(self, commit=True):
        user = super().save(commit=False)
        if commit:
            user.save()
            # set() substitui o conjunto de permissões do usuário pelo escolhido
            self.instance.user_permissions.set(self.cleaned_data.get('permissoes', []))
        return user
