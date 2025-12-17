from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("atividades", "0005_add_area_model_and_link"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="atividade",
            name="area_code",
        ),
    ]
