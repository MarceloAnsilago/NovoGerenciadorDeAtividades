# scripts/create_admin.py
import os
import django
from django.core.exceptions import ValidationError

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")  # ajuste
django.setup()

from django.contrib.auth import get_user_model  # noqa: E402

User = get_user_model()

username = os.getenv("DJANGO_SUPERUSER_USERNAME", "admin")
email = os.getenv("DJANGO_SUPERUSER_EMAIL", "celosmg1@gmail.com")
password = os.getenv("DJANGO_SUPERUSER_PASSWORD", "admin123")

u, created = User.objects.get_or_create(username=username, defaults={"email": email, "is_staff": True, "is_superuser": True})
if not created:
    # garante flags de admin mesmo se já existir
    changed = False
    if not u.is_staff:
        u.is_staff = True; changed = True
    if not u.is_superuser:
        u.is_superuser = True; changed = True
    if u.email != email:
        u.email = email; changed = True
    if changed:
        u.save(update_fields=["email", "is_staff", "is_superuser"])

# sempre (re)define a senha para garantir acesso
try:
    u.set_password(password)
    u.full_clean()
    u.save()
    print(f"Admin pronto: user='{username}', email='{email}'")
except ValidationError as e:
    print(f"Falha ao validar admin: {e}")
    raise
