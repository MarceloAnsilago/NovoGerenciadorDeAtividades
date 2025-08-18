from django import forms
from django.contrib.auth.models import Permission, User

class PermissoesUsuarioForm(forms.ModelForm):
    permissoes = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Permissões"
    )

    class Meta:
        model = User
        fields = []  # não editaremos outros campos do User

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Marca as permissões atuais
        if self.instance and self.instance.pk:
            self.fields['permissoes'].initial = self.instance.user_permissions.all()

    def save(self, commit=True):
        user = super().save(commit=False)
        # Atualiza permissões de acordo com o campo
        if commit:
            user.save()
            user.user_permissions.set(self.cleaned_data['permissoes'])
        return user
