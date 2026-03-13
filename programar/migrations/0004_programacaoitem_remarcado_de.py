from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("programar", "0003_programacaoitem_nao_realizada_justificada"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
ALTER TABLE programar_atividades_programacaoitem
ADD COLUMN IF NOT EXISTS remarcado_de_id bigint NULL;

CREATE INDEX IF NOT EXISTS idx_progitem_remarcado_de
ON programar_atividades_programacaoitem (remarcado_de_id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_progitem_remarcado_de'
    ) THEN
        ALTER TABLE programar_atividades_programacaoitem
        ADD CONSTRAINT fk_progitem_remarcado_de
        FOREIGN KEY (remarcado_de_id)
        REFERENCES programar_atividades_programacaoitem(id)
        ON DELETE SET NULL;
    END IF;
END $$;
            """,
            reverse_sql="""
ALTER TABLE programar_atividades_programacaoitem
DROP CONSTRAINT IF EXISTS fk_progitem_remarcado_de;

DROP INDEX IF EXISTS idx_progitem_remarcado_de;

ALTER TABLE programar_atividades_programacaoitem
DROP COLUMN IF EXISTS remarcado_de_id;
            """,
        ),
    ]
