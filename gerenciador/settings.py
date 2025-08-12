from pathlib import Path
import os
from dotenv import load_dotenv
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# Segurança
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "chave-insegura-para-dev")
DEBUG = os.getenv("DEBUG", "0") == "1"
ALLOWED_HOSTS = [h for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h]

# Apps
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "organizacao",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "gerenciador.urls"
WSGI_APPLICATION = "gerenciador.wsgi.application"

# Templates
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                # nosso contexto de vínculos/permissões:
                "organizacao.context_processors.contexto_vinculo",
            ],
        },
    },
]

# Banco (URL única OU variáveis separadas)
db_url = os.getenv("SUPABASE_DB_URL")
if db_url:
    p = urlparse(db_url)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "HOST": p.hostname,
            "NAME": p.path.lstrip("/"),
            "USER": p.username,
            "PASSWORD": p.password,
            "PORT": p.port or 5432,
            "OPTIONS": {"sslmode": "require"},
        }
    }
else:
    # variáveis separadas (use user com project ref no pooler, ex: postgres.<PROJECT_REF>)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "HOST": os.getenv("SUPABASE_DB_HOST"),
            "NAME": os.getenv("SUPABASE_DB_NAME"),
            "USER": os.getenv("SUPABASE_DB_USER"),
            "PASSWORD": os.getenv("SUPABASE_DB_PASSWORD"),
            "PORT": os.getenv("SUPABASE_DB_PORT", 5432),
            "OPTIONS": {"sslmode": "require"},
        }
    }

# Senhas
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Locale
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Porto_Velho"
USE_I18N = True
USE_TZ = True

# Static
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Configurações de autenticação
LOGIN_URL = '/accounts/login/'         # ou '/admin/login/'
LOGIN_REDIRECT_URL = '/'               # pós-login vai pro dashboard
LOGOUT_REDIRECT_URL = '/accounts/login/'