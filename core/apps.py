# core/apps.py
from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'  # deve bater com a pasta e com INSTALLED_APPS

    def ready(self):
        import core.signals  # ajuste 'core' conforme nome real da app
