# app/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import UserProfile, Policy

@receiver(post_save, sender=UserProfile)
def create_policy_for_user_profile(sender, instance, created, **kwargs):
    if created and not hasattr(instance, 'policy'):
        Policy.objects.create(user_profile=instance)