from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("programar", "0004_programacaoitem_remarcado_de"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_class
        WHERE relname = 'programar_atividades_programacaoitem'
    ) THEN
        ALTER TABLE programar_atividades_programacaoitem
        ADD COLUMN IF NOT EXISTS cancelada boolean NOT NULL DEFAULT FALSE;

        CREATE INDEX IF NOT EXISTS idx_progitem_cancelada
        ON programar_atividades_programacaoitem (cancelada);
    END IF;
END $$;
            """,
            reverse_sql="""
DROP INDEX IF EXISTS idx_progitem_cancelada;

ALTER TABLE programar_atividades_programacaoitem
DROP COLUMN IF EXISTS cancelada;
            """,
        ),
    ]
