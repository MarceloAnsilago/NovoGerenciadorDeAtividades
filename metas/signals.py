from django.db.models.signals import post_save
from django.dispatch import receiver

from atividades.models import Atividade

from .models import Meta


@receiver(post_save, sender=Atividade)
def sync_meta_title_with_atividade(sender, instance, **kwargs):
    titulo = (instance.titulo or "").strip()
    if not titulo:
        return
    Meta.objects.filter(atividade=instance).exclude(titulo=titulo).update(titulo=titulo)
