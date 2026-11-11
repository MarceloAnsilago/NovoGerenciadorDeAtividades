#!/usr/bin/env bash
# Install a reviewed copy outside the checkout. Never execute a fetched script.
set -Eeuo pipefail
umask 077
export GIT_TERMINAL_PROMPT=0 PIP_NO_INPUT=1
project=/srv/gerenciador/app
venv=/srv/gerenciador/venv
backups=/srv/gerenciador/deploy-backups
state=/srv/gerenciador/deploy-state
service=gerenciador.service
branch=oracle-production
remote=https://github.com/MarceloAnsilago/NovoGerenciadorDeAtividades.git
health_url=https://gerenciador.celosmg.com.br/login/
dry=0
retry=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) dry=1 ;;
        --retry-failed) retry=1 ;;
        *) echo 'Uso: oracle.sh [--dry-run] [--retry-failed]' >&2; exit 2 ;;
    esac
done
log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*"; }
die() { log "$*" >&2; exit 1; }
cd "$project"
test "$(git rev-parse --show-toplevel)" = "$project" || die 'Checkout inesperado.'
# Lock the Git directory itself: dry-run does not create a lock/state file.
exec 9< .git
flock -n 9 || { log 'Outra execucao esta em andamento.'; exit 0; }
test -f .env && test -x "$venv/bin/python" || die '.env ou Python ausente.'
test ! -L "$venv" && test ! -L staticfiles || die 'Venv/staticfiles simbolicos exigem estrategia de backup especifica.'
test -z "$(git status --porcelain --untracked-files=normal)" || die 'Checkout sujo; revise manualmente.'
test -z "$(git ls-files -- .env '.env.*' media staticfiles '*.sqlite3' '*.db')" || die 'Configuracao/dados versionados; remova do indice em manutencao antes de instalar.'
old=$(git rev-parse HEAD)
test "$(git remote get-url origin)" = "$remote" || die 'origin inesperado (use HTTPS e credencial somente leitura fora do Git).'
work=$(mktemp -d)
cleanup() { rm -rf -- "$work"; }
trap cleanup EXIT
# Fetch into a temporary repository, leaving even refs/FETCH_HEAD untouched in dry-run.
git clone --quiet --shared --no-checkout "$project" "$work/repo"
git -C "$work/repo" fetch --quiet --no-tags "$remote" "refs/heads/$branch"
target=$(git -C "$work/repo" rev-parse FETCH_HEAD)
log "Instalado=$old; producao=$target"
if test -f "$state/in-progress"; then
    die 'Transacao interrompida. Revise in-progress e backup; recuperacao manual obrigatoria.'
fi
if test "$target" = "$old"; then
    log 'Sem atualizacoes; nenhum reinicio.'; exit 0
fi
git -C "$work/repo" merge-base --is-ancestor "$old" "$target" || die 'Atualizacao recusada: nao e fast-forward.'
test -z "$(git -C "$work/repo" ls-tree -r --name-only "$target" -- .env '.env.*' media staticfiles '*.sqlite3' '*.db')" || die 'Candidato contem configuracao ou dados protegidos.'
test -z "$(git -C "$work/repo" ls-tree -r "$target" | awk '$1 == "120000" {print}')" || die 'Candidato contem links simbolicos; revise manualmente.'
if test -f "$state/failed/$target" && test "$retry" = 0; then
    log 'Versao anteriormente recusada; exige revisao e --retry-failed.'; exit 0
fi
deps=0
git -C "$work/repo" diff --quiet "$old" "$target" -- requirements.txt || deps=1
if test "$dry" = 1; then
    log "DRY-RUN: fast-forward permitido; dependencias alteradas=$deps."
    log 'Nenhuma alteracao na instalacao, refs, estado, banco ou servicos. Validacoes Django do candidato somente no deploy real.'
    exit 0
fi
sudo -n -l /usr/bin/systemctl restart "$service" >/dev/null
systemctl is-active --quiet "$service" || die 'Servico precisa estar ativo antes do deploy.'
mkdir -p "$state/failed" "$backups"
backup=$(mktemp -d "$backups/$(date -u +%Y%m%dT%H%M%SZ)-${target:0:12}-XXXXXX")
printf '%s\n' "$old" > "$backup/previous-sha"
git archive "$old" | gzip > "$backup/code.tar.gz"
if test -d staticfiles; then cp -a staticfiles "$backup/staticfiles"; fi
if test "$deps" = 1; then cp -a "$venv" "$backup/venv"; fi
printf '%s\n%s\n%s\n' "$old" "$target" "$backup" > "$state/in-progress"
mutated=0
restarted=0
health() {
    local code
    systemctl is-active --quiet "$service" || return 1
    code=$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
        --connect-timeout 5 --max-time 15 --resolve gerenciador.celosmg.com.br:443:127.0.0.1 \
        --header 'Cache-Control: no-cache' "$health_url") || return 1
    test "$code" = 200
}
rollback() {
    local rc=$?
    trap - ERR INT TERM
    set +e
    printf '%s backup=%s\n' "$(date -u +%FT%TZ)" "$backup" > "$state/failed/$target"
    log "FALHA ($rc); restaurando $old. Backup: $backup"
    local ok=1
    if test "$mutated" = 1; then
        git restore --source="$old" --staged --worktree -- . || ok=0
        git update-ref HEAD "$old" || ok=0
        if test "$deps" = 1; then
            mv "$venv" "$backup/venv-failed" && mv "$backup/venv" "$venv" || ok=0
        fi
        if test -d staticfiles; then mv staticfiles "$backup/staticfiles-failed" || ok=0; fi
        if test -d "$backup/staticfiles"; then cp -a "$backup/staticfiles" staticfiles || ok=0; fi
        if test "$restarted" = 1; then
            sudo -n /usr/bin/systemctl restart "$service" || ok=0
            health || ok=0
        fi
    fi
    if test "$ok" = 1; then
        printf '%s %s rollback=%s\n' "$old" "$(date -u +%FT%TZ)" "$backup" > "$state/deployed.tmp" &&
            mv "$state/deployed.tmp" "$state/deployed" && rm -f "$state/in-progress" || ok=0
    fi
    if test "$ok" = 1; then
        log 'Rollback concluido; nenhum comando de escrita no banco foi executado.'
    else
        log 'ROLLBACK INCOMPLETO: intervencao obrigatoria; novas tentativas bloqueadas.'
    fi
    exit 1
}
trap rollback ERR
trap 'false' INT TERM
git fetch --quiet --no-tags "$work/repo" "$target"
mutated=1
git -c core.hooksPath=/dev/null merge --ff-only --no-overwrite-ignore "$target"
if test "$deps" = 1; then
    "$venv/bin/python" -m pip install --disable-pip-version-check -r requirements.txt
    "$venv/bin/python" -m pip check
fi
"$venv/bin/python" manage.py check
"$venv/bin/python" manage.py makemigrations --check --dry-run
"$venv/bin/python" manage.py migrate --check --noinput
"$venv/bin/python" manage.py collectstatic --noinput
restarted=1
sudo -n /usr/bin/systemctl restart "$service"
healthy=0
for attempt in {1..6}; do
    if health; then healthy=1; break; fi
    sleep 3
done
test "$healthy" = 1
printf '%s %s backup=%s\n' "$target" "$(date -u +%FT%TZ)" "$backup" > "$state/deployed.tmp"
mv "$state/deployed.tmp" "$state/deployed"
rm -f "$state/in-progress" "$state/failed/$target"
trap - ERR INT TERM
log "Publicado e verificado: $target"
