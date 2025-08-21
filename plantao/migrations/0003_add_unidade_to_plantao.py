# plantao/migrations/0003_add_unidade_to_plantao.py
from django.db import migrations, models
import django.db.models.deletion


def backfill_unidade(apps, schema_editor):
    Plantao = apps.get_model("plantao", "Plantao")
    Semana = apps.get_model("plantao", "Semana")
    SemanaServidor = apps.get_model("plantao", "SemanaServidor")
    Servidor = apps.get_model("servidores", "Servidor")

    for p in Plantao.objects.all():
        unidade_id = None
        semanas = Semana.objects.filter(plantao_id=p.id).order_by("ordem", "inicio")
        for s in semanas:
            ss_qs = SemanaServidor.objects.filter(semana_id=s.id).order_by("ordem")
            if not ss_qs.exists():
                continue
            first_ss = ss_qs.first()
            try:
                servidor = first_ss.servidor
            except Exception:
                servidor = None
            if servidor is not None:
                uid = getattr(servidor, "unidade_id", None)
                if uid:
                    unidade_id = uid
                    break
        if unidade_id:
            p.unidade_id = unidade_id
            p.save(update_fields=["unidade_id"])


def noop_reverse(apps, schema_editor):
    # não desfazemos o backfill automaticamente
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('plantao', '0002_plantao_nome_semana_semanaservidor_and_more'),
    ]

    operations = [
        migrations.AddField(
      
            model_name='plantao',
            name='unidade',
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.PROTECT,
                to='core.no',
            ),
        ),
        migrations.RunPython(backfill_unidade, noop_reverse),
    ]
