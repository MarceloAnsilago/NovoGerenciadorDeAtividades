"""Local tests only: no connection to the configured Supabase database.

Usage: python manage.py test descanso --settings=config.settings_test
"""
from .settings import *  # noqa: F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
        # Legacy programar migrations contain PostgreSQL-only DO blocks.
        # Build the disposable test schema from models; do not fake migrations.
        "TEST": {"MIGRATE": False},
    }
}
DEBUG = True
SECURE_SSL_REDIRECT = False
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
TEST_RUNNER = "config.test_runner.LocalSQLiteRunner"
