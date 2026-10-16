#!/usr/bin/env bash
# backup.sh: encrypted off-site database backups (spec §5 `backup`, ticket 34).
#
#   backup.sh dump     pg_dump -Fc | age -> rclone remote, then prune old dumps (nightly)
#   backup.sh ledger   do-not-send ledger (suppressions + unsubscribes) | age -> remote (hourly)
#   backup.sh list     list the dumps on the remote
#   backup.sh check    check tools, settings and that the remote is reachable
#
# The plaintext dump never touches the disk: pg_dump streams into age, and only the
# ciphertext is written (to a work directory) before the upload, so the upload can be retried
# and its size checked. The server holds only age *public* keys; the private key lives
# offline (docs/runbook.md "Backups"), so a stolen server or bucket reveals nothing.
#
# Settings (environment; /etc/openfoodalerts/backup.env under systemd):
#   BACKUP_DATABASE_URL    libpq URL, read-only role ofa_backup (pg_read_all_data)   required
#   BACKUP_AGE_RECIPIENTS  space-separated age public keys (age1...)                 required
#   BACKUP_REMOTE          rclone path, e.g. ofabackup:openfoodalerts-backups/prod   required
#   BACKUP_PREFIX          file name prefix (default: ofa)
#   BACKUP_KEEP_DAYS       delete dumps older than this; 0 = never (bucket lifecycle) (30)
#   BACKUP_KEEP_MIN        always keep at least this many newest dumps (7)
#   BACKUP_WORK_DIR        where the ciphertext is staged (default: $CACHE_DIRECTORY or /var/tmp)
#   RCLONE_CONFIG_<REMOTE>_*  the rclone remote itself (see ops/env/backup.env.example)
#
# Exit status: 0 on success, non-zero on any failure (the unit then reports to the heartbeat).
set -euo pipefail
umask 077
export LC_ALL=C

PREFIX=${BACKUP_PREFIX:-ofa}
KEEP_DAYS=${BACKUP_KEEP_DAYS:-30}
KEEP_MIN=${BACKUP_KEEP_MIN:-7}
WORK_BASE=${BACKUP_WORK_DIR:-${CACHE_DIRECTORY:-/var/tmp}}

log() { printf '{"event":"backup","mode":"%s","msg":"%s"}\n' "${MODE:-?}" "$*" >&2; }
die() { log "error: $*"; exit 1; }

need_tools() {
    local tool
    for tool in "$@"; do
        command -v "$tool" >/dev/null 2>&1 || die "missing tool: $tool"
    done
}

need_settings() {
    [ -n "${BACKUP_DATABASE_URL:-}" ] || die "BACKUP_DATABASE_URL is not set"
    [ -n "${BACKUP_AGE_RECIPIENTS:-}" ] || die "BACKUP_AGE_RECIPIENTS is not set"
    [ -n "${BACKUP_REMOTE:-}" ] || die "BACKUP_REMOTE is not set"
    case $KEEP_DAYS in '' | *[!0-9]*) die "BACKUP_KEEP_DAYS must be a number" ;; esac
    case $KEEP_MIN in '' | *[!0-9]*) die "BACKUP_KEEP_MIN must be a number" ;; esac
    REMOTE=${BACKUP_REMOTE%/}
    recipients=()
    local key
    for key in $BACKUP_AGE_RECIPIENTS; do
        case $key in
            age1*) recipients+=(-r "$key") ;;
            *) die "BACKUP_AGE_RECIPIENTS: not an age public key: ${key:0:12}..." ;;
        esac
    done
    [ ${#recipients[@]} -gt 0 ] || die "BACKUP_AGE_RECIPIENTS has no keys"
}

make_work_dir() {
    WORK=$(mktemp -d "$WORK_BASE/ofa-backup.XXXXXX")
    trap 'rm -rf "$WORK"' EXIT
}

# Upload a local file and check that the remote copy has the same size.
upload() {
    local file=$1 dest=$2 local_size remote_size
    rclone copyto --retries 5 --low-level-retries 10 "$file" "$dest"
    local_size=$(stat -c %s "$file")
    remote_size=$(rclone size --json "$dest" | sed -E 's/.*"bytes":([0-9]+).*/\1/')
    [ "$remote_size" = "$local_size" ] ||
        die "size check failed for $dest: local $local_size, remote ${remote_size:-?}"
}

do_dump() {
    need_tools pg_dump age rclone sha256sum
    need_settings
    make_work_dir
    local stamp name file
    stamp=$(date -u +%Y%m%dT%H%M%SZ)
    name="$PREFIX-$stamp.dump.age"
    file="$WORK/$name"

    log "dumping to $name"
    # pipefail: a failing pg_dump fails the pipeline even though age exits 0.
    pg_dump --format=custom --no-password --dbname="$BACKUP_DATABASE_URL" |
        age --encrypt "${recipients[@]}" --output "$file"
    [ -s "$file" ] || die "empty dump"

    (cd "$WORK" && sha256sum "$name" >"$name.sha256")
    upload "$file" "$REMOTE/daily/$name"
    upload "$file.sha256" "$REMOTE/daily/$name.sha256"
    log "uploaded $name ($(stat -c %s "$file") bytes)"

    prune
}

# Delete dumps older than KEEP_DAYS, but never the KEEP_MIN newest ones: if backups have been
# failing for weeks, the last good dumps must survive. Ages come from the UTC timestamp in
# the file name, not from the storage's modification times.
prune() {
    if [ "$KEEP_DAYS" -eq 0 ]; then
        log "pruning disabled (BACKUP_KEEP_DAYS=0)"
        return
    fi
    local cutoff dumps old count=0 stamp f
    cutoff="$PREFIX-$(date -u -d "-$KEEP_DAYS days" +%Y%m%dT%H%M%SZ).dump.age"
    mapfile -t dumps < <(rclone lsf --files-only --include "$PREFIX-*.dump.age" "$REMOTE/daily" | sort)
    [ ${#dumps[@]} -gt "$KEEP_MIN" ] || { log "pruning: ${#dumps[@]} dumps, nothing to do"; return; }
    old=("${dumps[@]:0:${#dumps[@]}-KEEP_MIN}")
    for f in "${old[@]}"; do
        stamp=${f#"$PREFIX"-}
        case $stamp in [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z.dump.age) ;; *) continue ;; esac
        if [[ "$f" < "$cutoff" ]]; then
            rclone deletefile "$REMOTE/daily/$f"
            rclone deletefile "$REMOTE/daily/$f.sha256" 2>/dev/null || true
            count=$((count + 1))
        fi
    done
    log "pruned $count dumps older than $KEEP_DAYS days"
}

# Everything a restore needs to honour requests made after the dump it restores: every
# address on the do-not-send list and every unsubscribed Subscription (docs/privacy/ropa.md
# §2.6). Keyed hashes and random ids only, no addresses; encrypted like the dumps.
LEDGER_SQL="COPY (
    SELECT 'suppressed' AS kind, email_hash, NULL::uuid AS subscription_id, created_at AS at
    FROM email_suppressions
    UNION ALL
    SELECT 'unsubscribed', email_hash, id, unsubscribed_at
    FROM subscriptions WHERE status = 'unsubscribed'
    ORDER BY kind, at
) TO STDOUT WITH (FORMAT csv, HEADER)"

do_ledger() {
    need_tools psql age rclone
    need_settings
    make_work_dir
    local file="$WORK/do-not-send.csv.age"
    psql --no-psqlrc --no-password --quiet --set ON_ERROR_STOP=1 \
        --dbname="$BACKUP_DATABASE_URL" --command "$LEDGER_SQL" |
        age --encrypt "${recipients[@]}" --output "$file"
    [ -s "$file" ] || die "empty ledger"
    upload "$file" "$REMOTE/ledger/do-not-send.csv.age"
    log "ledger uploaded"
}

do_list() {
    need_tools rclone
    need_settings
    rclone lsl --include "$PREFIX-*.dump.age" "$REMOTE/daily" | sort -k2,3
    rclone lsl "$REMOTE/ledger" 2>/dev/null || true
}

do_check() {
    need_tools pg_dump psql age rclone sha256sum
    need_settings
    psql --no-psqlrc --no-password --quiet --set ON_ERROR_STOP=1 --dbname="$BACKUP_DATABASE_URL" \
        --tuples-only --command "SELECT 'database ok: ' || current_user || '@' || current_database()"
    echo "age recipients: $((${#recipients[@]} / 2))"
    rclone lsd "$REMOTE" >/dev/null 2>&1 || rclone mkdir "$REMOTE"
    echo "remote ok: $REMOTE"
}

MODE=${1:-}
case $MODE in
    dump) do_dump ;;
    ledger) do_ledger ;;
    list) do_list ;;
    check) do_check ;;
    *)
        echo "usage: backup.sh dump|ledger|list|check" >&2
        exit 2
        ;;
esac
