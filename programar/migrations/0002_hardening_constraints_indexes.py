from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("programar", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_prog_data_unidade'
    ) AND EXISTS (
        SELECT 1
        FROM pg_class
        WHERE relname = 'programar_atividades_programacao'
    ) THEN
        ALTER TABLE programar_atividades_programacao
        ADD CONSTRAINT uq_prog_data_unidade UNIQUE (data, unidade_id);
    END IF;
END $$;
            """,
            reverse_sql="""
ALTER TABLE programar_atividades_programacao
DROP CONSTRAINT IF EXISTS uq_prog_data_unidade;
            """,
        ),
        migrations.RunSQL(
            sql="""
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_prog_item_servidor'
    ) AND EXISTS (
        SELECT 1
        FROM pg_class
        WHERE relname = 'programar_atividades_programacaoitemservidor'
    ) THEN
        ALTER TABLE programar_atividades_programacaoitemservidor
        ADD CONSTRAINT uq_prog_item_servidor UNIQUE (item_id, servidor_id);
    END IF;
END $$;
            """,
            reverse_sql="""
ALTER TABLE programar_atividades_programacaoitemservidor
DROP CONSTRAINT IF EXISTS uq_prog_item_servidor;
            """,
        ),
        migrations.RunSQL(
            sql="""
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_class
        WHERE relname = 'programar_atividades_programacao'
    ) THEN
        CREATE INDEX IF NOT EXISTS idx_prog_data
        ON programar_atividades_programacao (data);
        CREATE INDEX IF NOT EXISTS idx_prog_unidade
        ON programar_atividades_programacao (unidade_id);
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_class
        WHERE relname = 'programar_atividades_programacaoitem'
    ) THEN
        CREATE INDEX IF NOT EXISTS idx_progitem_meta
        ON programar_atividades_programacaoitem (meta_id);
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_class
        WHERE relname = 'programar_atividades_programacaoitemservidor'
    ) THEN
        CREATE INDEX IF NOT EXISTS idx_progitemservidor_servidor
        ON programar_atividades_programacaoitemservidor (servidor_id);
    END IF;
END $$;
            """,
            reverse_sql="""
DROP INDEX IF EXISTS idx_prog_data;
DROP INDEX IF EXISTS idx_prog_unidade;
DROP INDEX IF EXISTS idx_progitem_meta;
DROP INDEX IF EXISTS idx_progitemservidor_servidor;
            """,
        ),
    ]
