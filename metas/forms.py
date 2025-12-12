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
            "data_limite": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date", "class": "form-control"},
            ),
            "quantidade_alvo": forms.NumberInput(attrs={"class": "form-control"}),
            "descricao": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # garante que o input type=date use o formato ISO (YYYY-MM-DD) para preencher o valor inicial
        self.fields["data_limite"].input_formats = ["%Y-%m-%d", "%d/%m/%Y"]

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
