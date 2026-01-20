from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("descanso", "0001_initial"),
        ("core", "0006_alter_no_options"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="FeriadoCadastro",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("descricao", models.CharField(max_length=120)),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                ("criado_por", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="feriados_cadastros_criados", to=settings.AUTH_USER_MODEL)),
                ("unidade", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="cadastros_feriados", to="core.no")),
            ],
            options={
                "ordering": ["-criado_em", "-id"],
            },
        ),
        migrations.CreateModel(
            name="Feriado",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("data", models.DateField()),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                ("criado_por", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="feriados_criados", to=settings.AUTH_USER_MODEL)),
                ("cadastro", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="feriados", to="descanso.feriadocadastro")),
            ],
            options={
                "ordering": ["data", "id"],
            },
        ),
        migrations.AddIndex(
            model_name="feriadocadastro",
            index=models.Index(fields=["unidade", "descricao"], name="descanso_fe_unidade_6b8f0c_idx"),
        ),
        migrations.AddIndex(
            model_name="feriado",
            index=models.Index(fields=["cadastro", "data"], name="descanso_fe_cadastro_d3c3aa_idx"),
        ),
        migrations.AddConstraint(
            model_name="feriado",
            constraint=models.UniqueConstraint(fields=("cadastro", "data"), name="uniq_feriado_cadastro_data"),
        ),
    ]
