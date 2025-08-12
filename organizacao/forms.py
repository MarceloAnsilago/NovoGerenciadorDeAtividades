from django import forms
from django.contrib.auth.models import User
from .models import PerfilUsuario, Unidade, PerfilPolitica

class PerfilUsuarioForm(forms.ModelForm):
    usuario = forms.ModelChoiceField(
        queryset=User.objects.order_by("username"),
        label="Usuário",
    )
    unidade = forms.ModelChoiceField(
        queryset=Unidade.objects.order_by("nome"),
        label="Unidade",
    )
    perfil_politica = forms.ModelChoiceField(
        queryset=PerfilPolitica.objects.order_by("nome"),
        label="Política",
        required=False,
        help_text="Opcional. Se vazio, o vínculo não terá política associada."
    )

    class Meta:
        model = PerfilUsuario
        fields = ["usuario", "unidade", "perfil_politica", "alcance"]
        widgets = {
            "alcance": forms.Select(attrs={"class": "form-select"}),
        }


class UsuarioCreateForm(forms.ModelForm):
    password1 = forms.CharField(label="Senha", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirme a senha", widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "is_active", "is_staff"]
        labels = {
            "username": "Usuário",
            "first_name": "Nome",
            "last_name": "Sobrenome",
            "email": "E-mail",
            "is_active": "Ativo",
            "is_staff": "Pode acessar o admin?",
        }

    def clean_username(self):
        u = self.cleaned_data["username"]
        if User.objects.filter(username__iexact=u).exists():
            raise forms.ValidationError("Nome de usuário já existe.")
        return u

    def clean(self):
        data = super().clean()
        if data.get("password1") != data.get("password2"):
            self.add_error("password2", "As senhas não conferem.")
        return data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user
