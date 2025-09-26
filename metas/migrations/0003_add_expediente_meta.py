from django.db import migrations
from django.utils import timezone

EXPEDIENTE_ID = 999909

def create_expediente(apps, schema_editor):
    Meta = apps.get_model("metas", "Meta")
    User = apps.get_model("auth", "User")
    Unidade = apps.get_model("core", "No")

    if not Meta.objects.filter(id=EXPEDIENTE_ID).exists():
        # tenta pegar primeiro usuário e unidade só para não quebrar constraints
        user = User.objects.first()
        unidade = Unidade.objects.first()

        Meta.objects.create(
            id=EXPEDIENTE_ID,
            titulo="Expediente Administrativo",
            descricao="Meta padrão do sistema",
            quantidade_alvo=0,
            data_limite=None,
            criado_em=timezone.now(),
            encerrada=False,
            atividade_id=None,  # sem atividade vinculada
            criado_por_id=user.id if user else 1,  # fallback: 1
            unidade_criadora_id=unidade.id if unidade else 1,  # fallback: 1
        )

def delete_expediente(apps, schema_editor):
    Meta = apps.get_model("metas", "Meta")
    Meta.objects.filter(id=EXPEDIENTE_ID).delete()

class Migration(migrations.Migration):

    dependencies = [
        ("metas", "0002_alter_meta_atividade_alter_meta_options_and_more"),
    ]

    operations = [
        migrations.RunPython(create_expediente, delete_expediente),
    ]
