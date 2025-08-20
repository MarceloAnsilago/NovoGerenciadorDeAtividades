# descanso/forms.py
from django import forms
from django.core.exceptions import ValidationError
from .models import Descanso
from servidores.models import Servidor
from core.utils import get_unidade_atual_id

class DescansoForm(forms.ModelForm):
    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        unidade_id = get_unidade_atual_id(request) if request else None

        qs = Servidor.objects.select_related("unidade")
        if unidade_id:
            qs = qs.filter(unidade_id=unidade_id)
        else:
            # Se quiser obrigar contexto, troque para Servidor.objects.none()
            qs = qs.none()

        self.fields["servidor"].queryset = qs
        self.request = request  # caso queira usar depois

    class Meta:
        model = Descanso
        fields = ["servidor", "tipo", "data_inicio", "data_fim", "observacoes"]
        widgets = {
            "servidor": forms.Select(attrs={"class": "form-select"}),
            "tipo": forms.Select(attrs={"class": "form-select"}),
            "data_inicio": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "data_fim": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "observacoes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def clean_servidor(self):
        servidor = self.cleaned_data.get("servidor")
        unidade_id = get_unidade_atual_id(self.request) if self.request else None
        if unidade_id and servidor and servidor.unidade_id != unidade_id:
            raise ValidationError("Você não pode registrar descanso para servidor fora da unidade atual.")
        return servidor

    def clean(self):
        cleaned = super().clean()
        # delega as regras de período ao model.clean()
        if self.instance:
            self.instance.servidor = cleaned.get("servidor")
            self.instance.tipo = cleaned.get("tipo")
            self.instance.data_inicio = cleaned.get("data_inicio")
            self.instance.data_fim = cleaned.get("data_fim")
            self.instance.observacoes = cleaned.get("observacoes") or ""
            self.instance.clean()
        return cleaned
