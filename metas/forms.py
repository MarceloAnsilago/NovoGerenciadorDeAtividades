from django import forms
from .models import Meta

# metas/forms.py
from django import forms
from .models import Meta

class MetaForm(forms.ModelForm):
    class Meta:
        model = Meta
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
