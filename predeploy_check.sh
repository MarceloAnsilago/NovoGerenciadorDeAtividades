#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

log() {
  printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*"
}

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "command not found: $1"
}

is_true() {
  case "${1:-}" in
    1|true|TRUE|True|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

require_cmd python

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings}"

: "${DJANGO_SECRET_KEY:?DJANGO_SECRET_KEY is required}"
: "${DJANGO_ALLOWED_HOSTS:?DJANGO_ALLOWED_HOSTS is required}"

if is_true "${DJANGO_DEBUG:-False}"; then
  fail "DJANGO_DEBUG must be False for predeploy checks."
fi

if [ "${#DJANGO_SECRET_KEY}" -lt 50 ]; then
  fail "DJANGO_SECRET_KEY must have at least 50 chars."
fi

log "Django system checks"
python manage.py check
python manage.py check --deploy

log "Checking model drift (makemigrations --check --dry-run)"
python manage.py makemigrations --check --dry-run

log "Checking unapplied migrations"
UNAPPLIED="$(python manage.py showmigrations | grep -E '^\s*\[ \]' || true)"
if [ -n "$UNAPPLIED" ]; then
  echo "$UNAPPLIED"
  fail "There are unapplied migrations. Run python manage.py migrate."
fi

log "Bytecode compilation"
python -m compileall -q config core descanso metas plantao programar servidores atividades veiculos

log "Dependency audit"
if ! python -c "import pip_audit" >/dev/null 2>&1; then
  python -m pip install --quiet pip-audit
fi
python -m pip_audit -r requirements.txt

if is_true "${RUN_TESTS:-0}"; then
  log "Running tests"
  python -m pytest -q
fi

log "Predeploy checks PASSED"
