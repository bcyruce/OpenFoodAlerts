#!/usr/bin/env bash
# ofa-deploy: build one commit into a new release directory and switch to it (ticket 34).
#
#   sudo ofa-deploy SHA            deploy this commit (must be on origin/main or a tag)
#   sudo ofa-deploy --rollback     switch back to the previous release (no migration rollback)
#   sudo ofa-deploy --status       show releases and installed-unit drift
#
# Install it ROOT-OWNED outside the checkout, and re-install by hand when it changes:
#   install -m 755 -o root -g root ops/deploy/deploy.sh /usr/local/sbin/ofa-deploy
# The deploy user may run exactly this file through sudo (ops/deploy/sudoers). Never point
# sudo at a script inside /opt/openfoodalerts: the ofa user can write there.
#
# Layout (docs/runbook.md):
#   /opt/openfoodalerts/repo.git           bare mirror of the GitHub repository (user ofa)
#   /opt/openfoodalerts/releases/<time>-<sha>   full checkout per release: the web build reads
#                                          docs/ and db/seed/ (implementation-log ### 27)
#   /opt/openfoodalerts/current            symlink to the active release
#
# Steps: fetch -> export the commit -> uv sync -> backup (if migrations are pending) ->
# dbmate up + load-seeds -> pnpm install + next build -> switch `current` -> restart the
# website and check it answers -> prune old releases. Build steps run as the unprivileged
# user ofa through systemd-run, which reads the root-only env files itself. If the new
# website does not come up, the previous release is switched back automatically.
#
# Systemd units and nginx config are NOT installed by this script: a commit must not be able
# to change what runs as which user. It prints a warning when the release's copies differ
# from the installed ones; install them by hand (runbook "Updating units").
set -euo pipefail
umask 022

BASE=${OFA_BASE:-/opt/openfoodalerts}
REPO=$BASE/repo.git
RELEASES=$BASE/releases
CURRENT=$BASE/current
ENV_DIR=/etc/openfoodalerts
APP_USER=ofa
WEB_USER=ofa-web
KEEP=${OFA_KEEP_RELEASES:-3}
WEB_CHECK_URL=http://127.0.0.1:3000/en
BUILD_PATH=/usr/local/bin:/usr/bin:/bin

log() { printf '\033[1mofa-deploy:\033[0m %s\n' "$*" >&2; }
die() { log "error: $*"; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run as root (sudo ofa-deploy ...)"
exec 9>/run/lock/ofa-deploy.lock
flock -n 9 || die "another deploy is running"

# Run a command as $APP_USER in a transient unit; optional env file read by systemd.
as_app() { # as_app DIR ENVFILE|- CMD...
    local dir=$1 envfile=$2
    shift 2
    local props=(-p User="$APP_USER" -p WorkingDirectory="$dir"
        -E PATH="$BUILD_PATH" -E UV_PYTHON_INSTALL_DIR="$BASE/python" -E UV_CACHE_DIR="$BASE/cache/uv"
        -E npm_config_store_dir="$BASE/cache/pnpm-store" -E NEXT_TELEMETRY_DISABLED=1
        -E CI=1)
    [ "$envfile" = - ] || props+=(-p EnvironmentFile="$envfile")
    systemd-run --quiet --pipe --wait --collect --service-type=exec "${props[@]}" -- "$@"
}

releases_sorted() { find "$RELEASES" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort; }

restart_and_check() {
    systemctl restart ofa-web.service
    local _
    for _ in $(seq 1 30); do
        if curl --silent --fail --max-time 5 --output /dev/null "$WEB_CHECK_URL"; then
            log "website answers on $WEB_CHECK_URL"
            return 0
        fi
        sleep 2
    done
    return 1
}

switch_to() { # switch_to RELEASE_DIR
    ln -sfn "$1" "$CURRENT.new"
    mv -Tf "$CURRENT.new" "$CURRENT"
    log "current -> $1"
}

unit_drift() {
    local dir=$1 f installed drift=0
    for f in "$dir"/ops/systemd/*.service "$dir"/ops/systemd/*.timer; do
        installed=/etc/systemd/system/$(basename "$f")
        if [ ! -e "$installed" ] || ! cmp -s "$f" "$installed"; then
            log "warning: $(basename "$f") differs from the installed unit"
            drift=1
        fi
    done
    if ! cmp -s "$dir/ops/systemd/openfoodalerts.tmpfiles.conf" /etc/tmpfiles.d/openfoodalerts.conf; then
        log "warning: tmpfiles config differs"; drift=1
    fi
    if [ -e /usr/local/sbin/ofa-deploy ] && ! cmp -s "$dir/ops/deploy/deploy.sh" /usr/local/sbin/ofa-deploy; then
        log "warning: ops/deploy/deploy.sh differs from /usr/local/sbin/ofa-deploy"; drift=1
    fi
    if [ -e /etc/nginx/sites-available/openfoodalerts.conf ] &&
        ! cmp -s "$dir/ops/nginx/openfoodalerts.conf" /etc/nginx/sites-available/openfoodalerts.conf; then
        log "warning: nginx config differs"; drift=1
    fi
    [ "$drift" -eq 0 ] || log "install the changed files by hand: docs/runbook.md \"Updating units\""
}

case ${1:-} in
    --status)
        log "releases:"; releases_sorted >&2
        log "current: $(readlink -f "$CURRENT" 2>/dev/null || echo none)"
        [ -e "$CURRENT" ] && unit_drift "$(readlink -f "$CURRENT")"
        exit 0
        ;;
    --rollback)
        now=$(readlink -f "$CURRENT")
        prev=''
        while read -r r; do
            [ "$RELEASES/$r" = "$now" ] && break
            prev=$RELEASES/$r
        done < <(releases_sorted)
        [ -n "$prev" ] || die "no release before $now"
        switch_to "$prev"
        restart_and_check || die "the previous release does not answer either; see journalctl -u ofa-web"
        log "rolled back. Database migrations are NOT rolled back (they are additive)."
        exit 0
        ;;
    '' | -*) die "usage: ofa-deploy SHA | --rollback | --status" ;;
esac

sha=$1
case $sha in *[!0-9a-f]* | '') die "SHA must be a hex commit id" ;; esac
if [ ${#sha} -lt 7 ] || [ ${#sha} -gt 40 ]; then die "SHA must have 7 to 40 hex digits"; fi

log "fetching"
as_app "$BASE" - git --git-dir="$REPO" fetch --prune --tags origin '+refs/heads/*:refs/heads/*'
full=$(runuser -u "$APP_USER" -- git --git-dir="$REPO" rev-parse --verify --quiet "$sha^{commit}") ||
    die "unknown commit $sha"
if ! runuser -u "$APP_USER" -- git --git-dir="$REPO" merge-base --is-ancestor "$full" main &&
    [ -z "$(runuser -u "$APP_USER" -- git --git-dir="$REPO" tag --points-at "$full")" ]; then
    die "$full is neither on main nor tagged"
fi

release=$RELEASES/$(date -u +%Y%m%dT%H%M%SZ)-${full:0:12}
log "building $full in $release"
install -d -o "$APP_USER" -g "$APP_USER" "$release"
# The inner script gets its values as $1..$3, hence the single quotes.
# shellcheck disable=SC2016
as_app "$release" - bash -c 'git --git-dir="$1" archive --format=tar "$2" | tar -x -C "$3" && printf "%s\n" "$2" >"$3/REVISION"' \
    _ "$REPO" "$full" "$release"

log "pipeline: uv sync"
as_app "$release/pipeline" - uv sync --locked --no-dev --compile-bytecode

log "database: migrations"
dbmate=(dbmate --migrations-dir "$release/db/migrations" --no-dump-schema)
status=$(as_app "$release" "$ENV_DIR/migrate.env" "${dbmate[@]}" --wait status || true)
applied=$(printf '%s\n' "$status" | sed -n 's/^Applied: *//p')
pending=$(printf '%s\n' "$status" | sed -n 's/^Pending: *//p')
[ -n "$pending" ] || die "could not read the migration status: $status"
if [ "$pending" -gt 0 ]; then
    # Nothing to back up on the very first deploy (no migration applied yet).
    if [ "${applied:-0}" -gt 0 ] && [ "${OFA_DEPLOY_SKIP_BACKUP:-0}" != 1 ]; then
        log "$pending pending migration(s): taking a backup first"
        systemctl start ofa-backup.service || die "pre-migration backup failed; not migrating"
    fi
    as_app "$release" "$ENV_DIR/migrate.env" "${dbmate[@]}" --wait up
fi
as_app "$release/pipeline" "$ENV_DIR/migrate.env" "$release/pipeline/.venv/bin/ofa" load-seeds

log "web: install and build"
as_app "$release/web" - pnpm install --frozen-lockfile
as_app "$release/web" "$ENV_DIR/web.env" env NODE_ENV=production pnpm build
# next start writes regenerated pages into .next; nothing else in the release is writable.
chown -R "$WEB_USER:$WEB_USER" "$release/web/.next"

previous=$(readlink -f "$CURRENT" 2>/dev/null || true)
switch_to "$release"
if ! restart_and_check; then
    log "the new release does not answer; rolling back"
    if [ -n "$previous" ] && [ -d "$previous" ]; then
        switch_to "$previous"
        restart_and_check || log "the previous release does not answer either"
    fi
    die "deploy of $full failed; see journalctl -u ofa-web"
fi
log "pipeline jobs pick up the new release on their next run"

unit_drift "$release"

mapfile -t all < <(releases_sorted)
if [ ${#all[@]} -gt "$KEEP" ]; then
    for r in "${all[@]:0:${#all[@]}-KEEP}"; do
        [ "$RELEASES/$r" = "$release" ] || [ "$RELEASES/$r" = "$previous" ] && continue
        rm -rf "${RELEASES:?}/$r"
        log "removed old release $r"
    done
fi
log "deployed $full"
