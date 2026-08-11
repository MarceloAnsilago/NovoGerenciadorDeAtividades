from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("programar", "0005_programacaoitem_cancelada"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="programacao",
            options={
                "managed": False,
                "permissions": [
                    ("reabrir_programacao_mes", "Pode reabrir programacao mensal encerrada"),
                ],
            },
        ),
    ]
