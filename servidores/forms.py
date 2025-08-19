# servidores/forms.py
from django import forms
from .models import Servidor

class ServidorForm(forms.ModelForm):
    class Meta:
        model = Servidor
        fields = ["nome", "telefone", "matricula", "ativo"]
        widgets = {
            "nome": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nome completo"}),
            "telefone": forms.TextInput(attrs={"class": "form-control", "placeholder": "(00) 00000-0000"}),
            "matricula": forms.TextInput(attrs={"class": "form-control", "placeholder": "Matrícula"}),
            "ativo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }