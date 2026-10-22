#!/usr/bin/env bash
set -Eeuo pipefail

project="$1"
venv="$2"
service="$3"
revision="$4"
branch="$5"
cd "$project"
test -f .env || { echo 'Arquivo .env ausente no servidor.' >&2; exit 1; }
test -x "$venv/bin/python"
test -z "$(git status --porcelain)" || { echo 'Existem alteracoes locais na Oracle; deploy interrompido.' >&2; exit 1; }
# Nunca permitir que a atualizacao sobrescreva configuracao ou uploads.
test -z "$(git ls-files -- .env media)" || { echo '.env ou media versionados; revise antes do deploy.' >&2; exit 1; }
sudo -n -l /usr/bin/systemctl restart "$service" >/dev/null
git fetch origin "$branch"
test "$(git rev-parse FETCH_HEAD)" = "$revision" || { echo 'O GitHub mudou durante o deploy. Execute novamente.' >&2; exit 1; }
test -z "$(git ls-tree -r --name-only "$revision" -- .env media)" || { echo 'Revisao inclui .env ou media; deploy interrompido.' >&2; exit 1; }
git merge-base --is-ancestor HEAD "$revision" || { echo 'Historico divergente na Oracle; revise manualmente.' >&2; exit 1; }
git merge --ff-only "$revision"
"$venv/bin/python" -m pip install -r requirements.txt
"$venv/bin/python" manage.py check
# Nao aplicar alteracoes no Supabase automaticamente.
"$venv/bin/python" manage.py migrate --check
"$venv/bin/python" manage.py collectstatic --noinput
sudo -n /usr/bin/systemctl restart "$service"
systemctl is-active --quiet "$service"
echo "Oracle atualizada para $revision."
