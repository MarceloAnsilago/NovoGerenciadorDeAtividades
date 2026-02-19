# metas/forms.py
from django import forms
from django.utils import timezone

from .models import Meta, MetaAlocacao


class MetaForm(forms.ModelForm):
    class Meta:
        model = Meta
        # usamos os campos reais do model
        fields = ["data_inicio", "data_limite", "quantidade_alvo", "descricao"]
        labels = {
            "data_inicio": "Data inicial",
            "quantidade_alvo": "Quantidade",
            "descricao": "Observacoes",
            "data_limite": "Data limite",
        }
        widgets = {
            "data_inicio": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date", "class": "form-control"},
            ),
            "data_limite": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date", "class": "form-control"},
            ),
            "quantidade_alvo": forms.NumberInput(attrs={"class": "form-control"}),
            "descricao": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # garante que os inputs type=date usem formato ISO (YYYY-MM-DD)
        self.fields["data_inicio"].input_formats = ["%Y-%m-%d", "%d/%m/%Y"]
        self.fields["data_limite"].input_formats = ["%Y-%m-%d", "%d/%m/%Y"]

        instance = getattr(self, "instance", None)
        # default apenas na criacao para nao sobrescrever metas antigas em edicao.
        if not self.is_bound and not getattr(instance, "pk", None):
            self.fields["data_inicio"].initial = timezone.localdate()

    def clean(self):
        """
        Impede reduzir a quantidade abaixo do total de atividades ja programadas
        e bloqueia edicao de metas encerradas.
        """
        cleaned = super().clean()
        instance = getattr(self, "instance", None)
        data_inicio = cleaned.get("data_inicio")
        data_limite = cleaned.get("data_limite")
        new_qty = cleaned.get("quantidade_alvo")

        if data_inicio and data_limite and data_inicio > data_limite:
            self.add_error("data_inicio", "A data inicial nao pode ser maior que a data limite.")
            self.add_error("data_limite", "A data limite nao pode ser menor que a data inicial.")

        # bloqueia edicoes em metas encerradas
        if instance and getattr(instance, "encerrada", False):
            raise forms.ValidationError("Esta meta ja foi encerrada e nao pode ser editada.")

        # valida quantidade x programacoes existentes
        if instance and getattr(instance, "pk", None) and new_qty is not None:
            programadas_total = 0
            try:
                from programar.models import ProgramacaoItem  # import local para evitar custo global

                programadas_total = ProgramacaoItem.objects.filter(meta_id=instance.id).count()
            except Exception:
                programadas_total = 0

            alocacoes_exist = instance.alocacoes.exists()
            alocacoes_count = instance.alocacoes.count() if alocacoes_exist else 0

            old_qty = getattr(instance, "quantidade_alvo", 0) or 0
            is_decrease = new_qty < old_qty
            if is_decrease and (alocacoes_exist or programadas_total):
                parts = []
                if alocacoes_exist:
                    parts.append(f"{alocacoes_count} meta(s) alocada(s)")
                if programadas_total:
                    parts.append(f"{programadas_total} atividade(s) programada(s)")
                joined = " e ".join(parts) if len(parts) > 1 else parts[0]
                self.add_error(
                    "quantidade_alvo",
                    (
                        f"Nao e possivel reduzir a meta porque ja existem {joined}. "
                        "Remova essas referencias antes de diminuir a quantidade alvo."
                    ),
                )

        return cleaned


class MetaAlocacaoForm(forms.ModelForm):
    class Meta:
        model = MetaAlocacao
        fields = ["quantidade_alocada", "observacao"]
        labels = {
            "quantidade_alocada": "Quantidade a alocar",
            "observacao": "Observacao",
        }
        widgets = {
            "quantidade_alocada": forms.NumberInput(attrs={"class": "form-control"}),
            "observacao": forms.TextInput(attrs={"class": "form-control"}),
        }
