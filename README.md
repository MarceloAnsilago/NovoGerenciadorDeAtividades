# Gerenciador de Atividades

## Desenvolvimento local

1. Crie um ambiente virtual e instale as dependências:
   ```
   python -m venv venv
   venv/Scripts/Activate
   pip install -r requirements.txt
   ```
2. Copie o `.env` existente, preencha os segredos (chave do Django, credenciais do Supabase, hosts permitidos) e rode as migrações/servidor:
   ```
   python manage.py migrate
   python manage.py runserver
   ```

3. Quando fizer alterações de front-end, atualize os arquivos estáticos:
   ```
   python manage.py collectstatic --noinput
   ```

## Deploy no Fly.io

1. Instale o [`flyctl`](https://fly.io/docs/getting-started/installing-flyctl/) e inicialize a aplicação (skip o `.toml` se já existir):
   ```
   flyctl launch --name gerenciador-de-atividades --region gru --dockerfile Dockerfile
   ```
2. Configure os segredos com `fly secrets set`. No mínimo defina:
   ```
fly secrets set DJANGO_SECRET_KEY="valor-secreto"
fly secrets set DJANGO_DEBUG="False"
fly secrets set DJANGO_ALLOWED_HOSTS="gerenciador-de-atividades.fly.dev"
   fly secrets set SUPABASE_DB_HOST=...
   fly secrets set SUPABASE_DB_NAME=...
   fly secrets set SUPABASE_DB_USER=...
   fly secrets set SUPABASE_DB_PASSWORD=...
   fly secrets set SUPABASE_DB_PORT=6543
   ```
   Inclua outros hosts/segredos adicionais conforme necessário.
3. O `Dockerfile` já instala as dependências, coleta os arquivos estáticos e expõe a porta 8080. A aplicação é servida pelo Gunicorn apontando para `config.wsgi:application`.
4. Compile e envie para Fly:
   ```
   flyctl deploy
   ```
5. Após o deploy, aplique quaisquer migrações manualmente:
   ```
   flyctl ssh console -- bash -lc "python manage.py migrate"
   ```

### Observações de produção

- O middleware WhiteNoise serve os arquivos estáticos em `staticfiles/`.
- O `fly.toml` configura as portas HTTP/HTTPS padrão e define concorrência com limites conservadores.
- Adapte o `DJANGO_ALLOWED_HOSTS` e `CSRF_TRUSTED_ORIGINS` no `.env` para incluir `*.fly.dev` ou outros domínios públicos.
