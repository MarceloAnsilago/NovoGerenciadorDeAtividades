from django import forms
from django.db.models import Q

from .models import Area, Atividade


class AtividadeForm(forms.ModelForm):
    class Meta:
        model = Atividade
        fields = ["titulo", "descricao", "area", "ativo"]
        widgets = {
            "descricao": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        unidade = kwargs.pop("unidade", None)
        super().__init__(*args, **kwargs)
        if "area" in self.fields:
            self.fields["area"].label = "Área"
            qs = Area.visible_to_unidade(unidade, active_only=True)
            if self.instance.pk and self.instance.area_id:
                qs = Area.objects.filter(pk=self.instance.area_id) | qs
            self.fields["area"].queryset = qs.distinct().order_by("nome")
            self.fields["area"].empty_label = "Selecione uma área"
            self.fields["area"].widget.attrs.update({"class": "form-select"})


class AreaForm(forms.ModelForm):
    class Meta:
        model = Area
        fields = ["nome", "descricao", "ativo"]
        widgets = {
            "nome": forms.TextInput(),
            "descricao": forms.Textarea(attrs={"rows": 3}),
            "ativo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        self.unidade = kwargs.pop("unidade", None)
        super().__init__(*args, **kwargs)
        self.fields["nome"].label = "Nome da área"
        self.fields["nome"].widget.attrs.update({"class": "form-control", "placeholder": "Ex.: Fiscalização"})
        self.fields["descricao"].label = "Descrição"
        self.fields["descricao"].required = False
        self.fields["descricao"].widget.attrs.update({"class": "form-control", "placeholder": "Detalhes opcionais"})
        self.fields["ativo"].label = "Ativa"

    def clean_nome(self):
        nome = self.cleaned_data["nome"]
        code = Area.build_code(nome)
        filters = Q(unidade__isnull=True, code__in=Area.default_codes())
        if self.unidade is not None:
            filters |= Q(unidade=self.unidade)
        qs = Area.objects.filter(code=code).filter(filters)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Já existe uma área cadastrada com este nome.")
        return nome

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.code = Area.build_code(instance.nome)
        if not instance.pk:
            instance.unidade = self.unidade
        if commit:
            instance.save()
            self.save_m2m()
        return instance
