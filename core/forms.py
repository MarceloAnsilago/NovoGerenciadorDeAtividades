# core/forms.py
from django import forms
from django.contrib.auth import get_user_model
User = get_user_model()

class NovoPerfilForm(forms.Form):
    username = forms.CharField(max_length=150, label="Usuário")
    first_name = forms.CharField(max_length=150, label="Nome", required=False)
    last_name = forms.CharField(max_length=150, label="Sobrenome", required=False)
    email = forms.EmailField(label="Email")
    group_name = forms.CharField(max_length=150, label="Nome do Perfil (Grupo)")

    allow_view_no   = forms.BooleanField(label="core.No — visualizar", required=False)
    allow_add_no    = forms.BooleanField(label="core.No — criar", required=False)
    allow_change_no = forms.BooleanField(label="core.No — alterar", required=False)
    allow_delete_no = forms.BooleanField(label="core.No — excluir", required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # inputs texto/email
        for name in ["username", "first_name", "last_name", "email", "group_name"]:
            self.fields[name].widget.attrs.update({"class": "form-control"})
        # checkboxes
        for name in ["allow_view_no", "allow_add_no", "allow_change_no", "allow_delete_no"]:
            self.fields[name].widget.attrs.update({"class": "form-check-input"})

    def clean_username(self):
        u = self.cleaned_data["username"]
        if User.objects.filter(username=u).exists():
            raise forms.ValidationError("Este nome de usuário já existe.")
        return u
