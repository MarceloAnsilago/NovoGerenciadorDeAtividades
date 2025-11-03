# servidores/forms.py
import re
from django import forms
from django.core.exceptions import ValidationError
from .models import Cargo, Servidor
from core.models import No  # modelo de unidade, caso precise exibir a unidade

PHONE_RE = re.compile(r'^\(?\d{2}\)?\s*\d{4,5}-?\d{4}$')

class ServidorForm(forms.ModelForm):
    """
    Form de Servidor:
    - por padrão NÃO mostra o campo `unidade` (assumimos que a view atribui a unidade pelo contexto).
    - se precisar exibir/editar a unidade em outros lugares, crie o form com `ServidorForm(show_unidade=True)`.
    """

    def __init__(self, *args, show_unidade: bool = False, **kwargs):
        super().__init__(*args, **kwargs)

        # labels / placeholders / classes
        self.fields["nome"].label = "Nome"
        self.fields["nome"].widget.attrs.update({"class": "form-control", "placeholder": "Nome completo", "autofocus": True})

        self.fields["telefone"].label = "Telefone"
        self.fields["telefone"].widget.attrs.update({"class": "form-control telefone-mask", "placeholder": "(00) 00000-0000"})

        if "cargo" in self.fields:
            self.fields["cargo"].label = "Cargo"
            self.fields["cargo"].empty_label = "Selecione um cargo"
            self.fields["cargo"].queryset = Cargo.objects.all().order_by("nome")
            self.fields["cargo"].widget.attrs.update({"class": "form-select"})

        self.fields["matricula"].label = "Matrícula"
        self.fields["matricula"].widget.attrs.update({"class": "form-control", "placeholder": "Matrícula"})

        self.fields["ativo"].label = "Ativo"

        # Se o model tiver campo unidade e quisermos exibir, adicionamos dinamicamente
        if show_unidade:
            # cria um field de escolha com as unidades (No)
            self.fields["unidade"] = forms.ModelChoiceField(
                queryset=No.objects.all().order_by("nome"),
                required=False,
                label="Unidade",
                widget=forms.Select(attrs={"class": "form-select"})
            )
        else:
            # assegura que não exista campo 'unidade' no form (defesa)
            self.fields.pop("unidade", None)

    class Meta:
        model = Servidor
        fields = ["nome", "cargo", "telefone", "matricula", "ativo"]  # mantenha `unidade` fora por padrão
        widgets = {
            "nome": forms.TextInput(),
            "cargo": forms.Select(),
            "telefone": forms.TextInput(),
            "matricula": forms.TextInput(),
            "ativo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        help_texts = {
            "matricula": "Número de matrícula (sem espaços desnecessários).",
            "telefone": "Formato esperado: (00) 00000-0000",
        }

    def clean_telefone(self):
        tel = (self.cleaned_data.get("telefone") or "").strip()
        if tel == "":
            return tel
        if not PHONE_RE.match(tel):
            raise ValidationError("Telefone em formato inválido. Use (00) 0000-0000 ou (00) 00000-0000.")
        return tel

    def clean_matricula(self):
        mat = (self.cleaned_data.get("matricula") or "").strip()
        # limite simples e trim
        if mat and len(mat) > 50:
            raise ValidationError("Matrícula muito longa.")
        return mat


class CargoForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['nome'].label = 'Nome do cargo'
        self.fields['nome'].widget.attrs.update({'class': 'form-control', 'placeholder': 'Ex.: Coordenador'})
        self.fields['descricao'].label = 'Descricao'
        self.fields['descricao'].required = False
        self.fields['descricao'].widget.attrs.update({'class': 'form-control', 'rows': 3, 'placeholder': 'Detalhes ou observacoes'})

    class Meta:
        model = Cargo
        fields = ['nome', 'descricao']
