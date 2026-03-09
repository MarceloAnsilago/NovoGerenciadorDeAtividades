from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("programar", "0002_hardening_constraints_indexes"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
ALTER TABLE programar_atividades_programacaoitem
ADD COLUMN IF NOT EXISTS nao_realizada_justificada boolean NOT NULL DEFAULT FALSE;
            """,
            reverse_sql="""
ALTER TABLE programar_atividades_programacaoitem
DROP COLUMN IF EXISTS nao_realizada_justificada;
            """,
        ),
    ]
