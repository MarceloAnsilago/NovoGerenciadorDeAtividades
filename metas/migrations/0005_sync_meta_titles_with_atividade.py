from django.db import migrations


def sync_meta_titles(apps, schema_editor):
    Meta = apps.get_model("metas", "Meta")
    Atividade = apps.get_model("atividades", "Atividade")

    atividade_titulos = {
        atividade_id: (titulo or "").strip()
        for atividade_id, titulo in Atividade.objects.values_list("id", "titulo")
    }

    metas_to_update = []
    metas_qs = Meta.objects.exclude(atividade_id__isnull=True).only("id", "atividade_id", "titulo")
    for meta in metas_qs.iterator():
        titulo_atividade = atividade_titulos.get(meta.atividade_id, "")
        if titulo_atividade and meta.titulo != titulo_atividade:
            meta.titulo = titulo_atividade
            metas_to_update.append(meta)

    if metas_to_update:
        Meta.objects.bulk_update(metas_to_update, ["titulo"], batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ("atividades", "0006_remove_area_code"),
        ("metas", "0004_meta_data_inicio"),
    ]

    operations = [
        migrations.RunPython(sync_meta_titles, migrations.RunPython.noop),
    ]
