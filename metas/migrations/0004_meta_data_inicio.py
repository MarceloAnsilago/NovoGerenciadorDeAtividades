from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("metas", "0003_add_expediente_meta"),
    ]

    operations = [
        migrations.AddField(
            model_name="meta",
            name="data_inicio",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name="meta",
            index=models.Index(fields=["data_inicio"], name="metas_meta_data_in_8c5929_idx"),
        ),
    ]
