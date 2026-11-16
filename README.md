# Gerenciador de Atividades

## Deploy na Oracle

A aplicação é hospedada na Oracle. O mecanismo de deploy consulta a branch
`oracle-production`; os procedimentos estão em [deploy/README.md](deploy/README.md).

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

## Observações de produção

- O middleware WhiteNoise serve os arquivos estáticos em `staticfiles/`.
- Configure `DJANGO_ALLOWED_HOSTS` e `CSRF_TRUSTED_ORIGINS` para o domínio público da aplicação.
