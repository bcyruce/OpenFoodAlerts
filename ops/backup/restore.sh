#!/usr/bin/env bash
# restore.sh: restore an encrypted dump made by backup.sh into a NEW database (ticket 34).
#
#   restore.sh [options] [DUMP | latest]
#
#   --identity FILE   age private key file (required; never stored on the server)
#   --target NAME     database to create and restore into (default: ofa_restore_<UTC time>)
#   --owner ROLE      owner of the new database (default: ofa)
#   --ledger          afterwards re-apply the do-not-send ledger (suppressions + unsubscribes
#                     newer than the dump; docs/privacy/ropa.md §2.6). Always use it for a
#                     restore that will go live
#   --drill           restore drill: restore, check, report, then DROP the target database
#   --list            list the dumps on the remote and exit
#
# It never touches an existing database: it refuses a target that exists. Going live with
# the restored database (stop services, rename databases, start services) is a separate,
# manual step in docs/runbook.md "Restore", so a mistake here cannot destroy production.
#
# Run it as a database superuser (CREATE DATABASE, extensions, ownership), e.g.
#   sudo -u postgres env BACKUP_REMOTE=... RCLONE_CONFIG_...=... restore.sh --identity key.txt latest
# Connection: the usual libpq variables (PGHOST, PGPORT, PGUSER, PGPASSWORD); default is the
# local socket as the current OS user. The plaintext dump is streamed straight into
# pg_restore and never written to disk; only the downloaded ciphertext is.
#
# Settings: BACKUP_REMOTE and BACKUP_PREFIX as for backup.sh; RESTORE_WORK_DIR (default /var/tmp).
set -euo pipefail
umask 077
export LC_ALL=C

here=$(dirname "$(readlink -f "$0")")
PREFIX=${BACKUP_PREFIX:-ofa}
WORK_BASE=${RESTORE_WORK_DIR:-/var/tmp}

identity=''
target=''
owner=ofa
ledger=0
drill=0
list=0
dump=''

usage() {
    sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//' >&2
    exit 2
}
log() { printf 'restore: %s\n' "$*" >&2; }
die() { log "error: $*"; exit 1; }

while [ $# -gt 0 ]; do
    case $1 in
        --identity) identity=${2:-}; shift 2 ;;
        --target) target=${2:-}; shift 2 ;;
        --owner) owner=${2:-}; shift 2 ;;
        --ledger) ledger=1; shift ;;
        --drill) drill=1; shift ;;
        --list) list=1; shift ;;
        -h | --help) usage ;;
        -*) die "unknown option $1" ;;
        *) dump=$1; shift ;;
    esac
done

for tool in rclone age pg_restore psql createdb dropdb sha256sum; do
    command -v "$tool" >/dev/null 2>&1 || die "missing tool: $tool"
done
[ -n "${BACKUP_REMOTE:-}" ] || die "BACKUP_REMOTE is not set"
REMOTE=${BACKUP_REMOTE%/}

if [ "$list" -eq 1 ]; then
    rclone lsl --include "$PREFIX-*.dump.age" "$REMOTE/daily" | sort -k2,3
    exit 0
fi

[ -n "$identity" ] || die "--identity FILE is required"
[ -r "$identity" ] || die "cannot read identity file $identity"
[ -n "$dump" ] || dump=latest
if [ "$dump" = latest ]; then
    dump=$(rclone lsf --files-only --include "$PREFIX-*.dump.age" "$REMOTE/daily" | sort | tail -n 1)
    [ -n "$dump" ] || die "no dumps found under $REMOTE/daily"
fi
case $dump in */* | *[!A-Za-z0-9._-]*) die "invalid dump name: $dump" ;; esac
[ -n "$target" ] || target="ofa_restore_$(date -u +%Y%m%d%H%M%S)"
case $target in *[!a-z0-9_]* | '') die "target must match [a-z0-9_]+: $target" ;; esac
case $owner in *[!a-z0-9_]* | '') die "owner must match [a-z0-9_]+: $owner" ;; esac

psql_admin() { psql --no-psqlrc --no-password --quiet --set ON_ERROR_STOP=1 --dbname=postgres "$@"; }
psql_target() { psql --no-psqlrc --no-password --quiet --set ON_ERROR_STOP=1 --dbname="$target" "$@"; }

exists=$(psql_admin --tuples-only --no-align \
    --command "SELECT 1 FROM pg_database WHERE datname = '$target'")
[ -z "$exists" ] || die "database $target already exists; choose another --target"
for role in "$owner" ofa_pipeline ofa_web ofa_mailer; do
    found=$(psql_admin --tuples-only --no-align --command "SELECT 1 FROM pg_roles WHERE rolname = '$role'")
    [ -n "$found" ] || die "role $role does not exist; create the roles first (docs/runbook.md)"
done

WORK=$(mktemp -d "$WORK_BASE/ofa-restore.XXXXXX")
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

log "downloading $dump"
rclone copyto --retries 5 "$REMOTE/daily/$dump" "$WORK/$dump"
if rclone copyto "$REMOTE/daily/$dump.sha256" "$WORK/$dump.sha256" 2>/dev/null; then
    (cd "$WORK" && sha256sum --check --quiet "$dump.sha256") || die "checksum mismatch for $dump"
    log "checksum ok"
else
    log "warning: no checksum file for $dump; continuing"
fi

log "creating database $target (owner $owner)"
createdb --no-password --template=template0 --encoding=UTF8 --owner="$owner" "$target"

log "restoring (single transaction; stops at the first error)"
age --decrypt --identity "$identity" "$WORK/$dump" |
    pg_restore --no-password --exit-on-error --single-transaction --dbname="$target"

if [ "$ledger" -eq 1 ]; then
    log "re-applying the do-not-send ledger"
    rclone copyto --retries 5 "$REMOTE/ledger/do-not-send.csv.age" "$WORK/ledger.csv.age" ||
        die "could not download the ledger; do NOT start the mailer jobs (docs/runbook.md)"
    age --decrypt --identity "$identity" "$WORK/ledger.csv.age" |
        psql_target --file "$here/apply-do-not-send.sql"
fi

log "checks"
psql_target --pset footer=off --command "
SELECT s.code AS source,
       count(n.id) AS notifications,
       max(n.first_seen_at) AS newest_first_seen,
       s.last_success_at
FROM sources s LEFT JOIN notifications n ON n.source_id = s.id
GROUP BY s.code, s.last_success_at ORDER BY s.code"
psql_target --pset footer=off --command "
SELECT (SELECT count(*) FROM raw_records) AS raw_records,
       (SELECT max(fetched_at) FROM raw_records) AS newest_raw_record,
       (SELECT count(*) FROM subscriptions) AS subscriptions,
       (SELECT count(*) FROM email_suppressions) AS suppressions,
       (SELECT count(*) FROM schema_migrations) AS migrations"

if [ "$drill" -eq 1 ]; then
    log "drill: dropping $target"
    dropdb --no-password "$target"
    log "drill passed: $dump restored and checked"
else
    log "restored $dump into $target. Next: docs/runbook.md \"Restore\" (go-live steps)."
fi
