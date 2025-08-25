# metas/forms.py
from django import forms
from .models import Meta, MetaAlocacao

class MetaForm(forms.ModelForm):
    class Meta:
        model = Meta
        # usamos os campos reais do model
        fields = ["data_limite", "quantidade_alvo", "descricao"]
        labels = {
            "quantidade_alvo": "Quantidade",
            "descricao": "Observações",
            "data_limite": "Data limite",
        }
        widgets = {
            "data_limite": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "quantidade_alvo": forms.NumberInput(attrs={"class": "form-control"}),
            "descricao": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
        }

class MetaAlocacaoForm(forms.ModelForm):
    class Meta:
        model = MetaAlocacao
        fields = ["quantidade_alocada", "observacao"]
        labels = {
            "quantidade_alocada": "Quantidade a alocar",
            "observacao": "Observação",
        }
        widgets = {
            "quantidade_alocada": forms.NumberInput(attrs={"class": "form-control"}),
            "observacao": forms.TextInput(attrs={"class": "form-control"}),
        }
