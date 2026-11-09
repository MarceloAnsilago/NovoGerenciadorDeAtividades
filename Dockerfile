FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel && \
    pip install -r requirements.txt

COPY . .
# Valores temporarios usados somente para coletar estaticos, sem acessar o banco.
RUN DJANGO_SECRET_KEY=build-only-not-for-runtime \
    SUPABASE_DB_NAME=build SUPABASE_DB_USER=build \
    SUPABASE_DB_PASSWORD=build SUPABASE_DB_HOST=localhost \
    python manage.py collectstatic --noinput

EXPOSE 8080

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "3", "--timeout", "120"]

