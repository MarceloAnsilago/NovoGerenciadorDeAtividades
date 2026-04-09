from django.db import migrations
from django.utils import timezone

EXPEDIENTE_ID = 999909


def create_expediente(apps, schema_editor):
    Meta = apps.get_model("metas", "Meta")
    User = apps.get_model("auth", "User")
    Unidade = apps.get_model("core", "No")

    if Meta.objects.filter(id=EXPEDIENTE_ID).exists():
        return

    user = User.objects.first()
    if user is None:
        user = User.objects.create(
            username="sistema.expediente",
            is_active=False,
        )

    unidade = Unidade.objects.first()
    if unidade is None:
        unidade = Unidade.objects.create(
            nome="Sistema",
            tipo="outro",
        )

    Meta.objects.create(
        id=EXPEDIENTE_ID,
        titulo="Expediente Administrativo",
        descricao="Meta padrao do sistema",
        quantidade_alvo=0,
        data_limite=None,
        criado_em=timezone.now(),
        encerrada=False,
        atividade_id=None,
        criado_por_id=user.id,
        unidade_criadora_id=unidade.id,
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
