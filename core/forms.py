from django import forms
from core.models import UserProfile, Policy

class UserProfileForm(forms.ModelForm):
    # Campos adicionais apenas para exibição (não salvos aqui)
    can_read = forms.BooleanField(disabled=True, required=False, label="Pode ler?")
    can_write = forms.BooleanField(disabled=True, required=False, label="Pode escrever?")
    scope = forms.ChoiceField(choices=Policy.SCOPE_CHOICES, disabled=True, required=False, label="Escopo")

    class Meta:
        model = UserProfile
        fields = ['user', 'unidade', 'senha_provisoria', 'ativado']  # Apenas os campos válidos de UserProfile

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance.pk and hasattr(self.instance, 'policy'):
            policy = self.instance.policy
            self.fields['can_read'].initial = policy.can_read
            self.fields['can_write'].initial = policy.can_write
            self.fields['scope'].initial = policy.scope
