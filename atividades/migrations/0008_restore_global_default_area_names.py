from django.db import migrations


def _restore_global_default_area_names(apps, schema_editor):
    Area = apps.get_model("atividades", "Area")
    defaults = {
        "ANIMAL": "Animal",
        "VEGETAL": "Vegetal",
        "ANIMAL_VEGETAL": "Animal e Vegetal",
        "APOIO": "Apoio",
        "OUTROS": "Outros",
    }
    for code, nome in defaults.items():
        Area.objects.filter(code=code, unidade__isnull=True).update(nome=nome, ativo=True)


class Migration(migrations.Migration):

    dependencies = [
        ("atividades", "0007_scope_area_by_unidade"),
    ]

    operations = [
        migrations.RunPython(_restore_global_default_area_names, migrations.RunPython.noop),
    ]
