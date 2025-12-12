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

    def clean(self):
        """
        Impede reduzir a quantidade abaixo do total de atividades já programadas
        e bloqueia edição de metas encerradas.
        """
        cleaned = super().clean()
        instance = getattr(self, "instance", None)
        new_qty = cleaned.get("quantidade_alvo")

        # bloqueia edições em metas encerradas
        if instance and getattr(instance, "encerrada", False):
            raise forms.ValidationError("Esta meta já foi encerrada e não pode ser editada.")

        # valida quantidade x programações existentes
        if instance and getattr(instance, "pk", None) and new_qty is not None:
            try:
                from programar.models import ProgramacaoItem  # import local para evitar custo global
                programadas_total = ProgramacaoItem.objects.filter(meta_id=instance.id).count()
            except Exception:
                programadas_total = 0

            if programadas_total and new_qty < programadas_total:
                self.add_error(
                    "quantidade_alvo",
                    (
                        f"Existem {programadas_total} atividade(s) desta meta já programadas. "
                        "Remova-as da programação antes de reduzir a quantidade alvo."
                    ),
                )

        return cleaned

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
