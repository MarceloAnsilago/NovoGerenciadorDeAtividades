from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("descanso", "0002_feriados"),
    ]

    operations = [
        migrations.AddField(
            model_name="feriado",
            name="descricao",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
    ]
