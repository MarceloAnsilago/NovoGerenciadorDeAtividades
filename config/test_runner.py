"""Build legacy unmanaged programar tables in the disposable SQLite test DB."""
from django.apps import apps
from django.conf import settings
from django.test.runner import DiscoverRunner


class LocalSQLiteRunner(DiscoverRunner):
    def setup_databases(self, **kwargs):
        if any(
            config["ENGINE"] != "django.db.backends.sqlite3" or config["NAME"] != ":memory:"
            for config in settings.DATABASES.values()
        ):
            raise RuntimeError("LocalSQLiteRunner exige SQLite em memoria para todos os bancos.")
        models = list(apps.get_app_config("programar").get_models())
        original = [(model, model._meta.managed) for model in models]
        try:
            for model in models:
                model._meta.managed = True
            return super().setup_databases(**kwargs)
        finally:
            for model, managed in original:
                model._meta.managed = managed
