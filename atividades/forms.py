# atividades/forms.py
from django import forms
from .models import Atividade

class AtividadeForm(forms.ModelForm):
    class Meta:
        model = Atividade
        fields = ["titulo", "descricao", "area", "ativo"]  # ← area aqui!
        widgets = {
            "descricao": forms.Textarea(attrs={"rows": 3}),
        }