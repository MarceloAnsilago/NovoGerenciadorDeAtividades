from django.db import migrations, models


def _create_area_defaults(area_model):
    defaults = [
        ("ANIMAL", "Animal"),
        ("VEGETAL", "Vegetal"),
        ("ANIMAL_VEGETAL", "Animal e Vegetal"),
        ("APOIO", "Apoio"),
        ("OUTROS", "Outros"),
    ]
    created = {}
    for code, name in defaults:
        area_obj, _ = area_model.objects.get_or_create(
            code=code,
            defaults={"nome": name, "ativo": True},
        )
        created[code] = area_obj
    return created


def _backfill_atividades(apps, schema_editor):
    Area = apps.get_model("atividades", "Area")
    Atividade = apps.get_model("atividades", "Atividade")

    created = _create_area_defaults(Area)

    for atividade in Atividade.objects.all():
        code = getattr(atividade, "area_code", None) or "OUTROS"
        area_obj = created.get(code)
        if area_obj is None:
            area_obj = Area.objects.create(code=code, nome=code.replace("_", " ").title(), ativo=True)
            created[code] = area_obj
        Atividade.objects.filter(pk=atividade.pk).update(area_id=area_obj.id)


class Migration(migrations.Migration):

    dependencies = [
        ("atividades", "0004_alter_atividade_titulo_add_unique_constraint"),
    ]

    operations = [
        migrations.CreateModel(
            name="Area",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=50, unique=True)),
                ("nome", models.CharField(max_length=120)),
                ("descricao", models.TextField(blank=True)),
                ("ativo", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["nome"],
                "verbose_name": "Área",
                "verbose_name_plural": "Áreas",
            },
        ),
        migrations.RenameField(
            model_name="atividade",
            old_name="area",
            new_name="area_code",
        ),
        migrations.AddField(
            model_name="atividade",
            name="area",
            field=models.ForeignKey(
                null=True,
                on_delete=models.PROTECT,
                related_name="atividades",
                to="atividades.area",
            ),
        ),
        migrations.RunPython(_backfill_atividades, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="atividade",
            name="area",
            field=models.ForeignKey(
                on_delete=models.PROTECT,
                related_name="atividades",
                to="atividades.area",
            ),
        ),
    ]
