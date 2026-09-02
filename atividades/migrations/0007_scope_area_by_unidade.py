import django.db.models.deletion
from django.db import migrations, models


def _scope_existing_custom_areas(apps, schema_editor):
    Area = apps.get_model("atividades", "Area")
    Atividade = apps.get_model("atividades", "Atividade")
    default_codes = {"ANIMAL", "VEGETAL", "ANIMAL_VEGETAL", "APOIO", "OUTROS"}

    for area in Area.objects.filter(unidade__isnull=True).exclude(code__in=default_codes):
        unidade_ids = list(
            Atividade.objects.filter(area_id=area.id)
            .exclude(unidade_origem_id__isnull=True)
            .values_list("unidade_origem_id", flat=True)
            .distinct()
        )
        if len(unidade_ids) == 1:
            Area.objects.filter(pk=area.pk).update(unidade_id=unidade_ids[0])


class Migration(migrations.Migration):

    dependencies = [
        ("atividades", "0006_remove_area_code"),
        ("core", "0006_alter_no_options"),
    ]

    operations = [
        migrations.AlterField(
            model_name="area",
            name="code",
            field=models.CharField(max_length=50),
        ),
        migrations.AddField(
            model_name="area",
            name="unidade",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="areas_atividade",
                to="core.no",
            ),
        ),
        migrations.RunPython(_scope_existing_custom_areas, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="area",
            constraint=models.UniqueConstraint(
                condition=models.Q(("unidade__isnull", True)),
                fields=("code",),
                name="area_unique_global_code",
            ),
        ),
        migrations.AddConstraint(
            model_name="area",
            constraint=models.UniqueConstraint(
                condition=models.Q(("unidade__isnull", False)),
                fields=("code", "unidade"),
                name="area_unique_code_unidade",
            ),
        ),
    ]
