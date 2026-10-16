#!/usr/bin/env bash
# init-db-and-secrets.sh: one-time database and secrets setup on a fresh server (ticket 34).
#
#   sudo ops/bootstrap/init-db-and-secrets.sh [CHECKOUT]     (CHECKOUT: repo with ops/env/)
#
# Run as root after installing PostgreSQL 16 locally (docs/runbook.md "Install"). It:
#   1. creates the database roles with LOGIN and random hex passwords:
#        ofa           owner of the database; runs migrations (no superuser, no CREATEROLE)
#        ofa_pipeline  ofa_web  ofa_mailer   application roles (spec §11.2); the migrations
#                      only create them when missing, so creating them here is equivalent
#        ofa_backup    read-only for pg_dump (member of pg_read_all_data)
#   2. creates the database `ofa` owned by `ofa`;
#   3. writes /etc/openfoodalerts/{migrate,pipeline,mailer,web,backup,heartbeat}.env from
#      ops/env/*.env.example (root:root, mode 600), with the passwords filled in and
#      OFA_HASH_PEPPER / OFA_TOKEN_SECRET generated once and shared by web and mailer.
#
# Safe to re-run: an existing env file is never overwritten and its role's password is
# left alone, so nothing that already works is rotated. API keys (Brevo, openFDA, model),
# the age recipients and the rclone remote are yours to add afterwards.
set -euo pipefail
umask 077

checkout=${1:-/opt/openfoodalerts/current}
templates=$checkout/ops/env
env_dir=/etc/openfoodalerts
db=ofa

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
[ -d "$templates" ] || { echo "no templates in $templates" >&2; exit 1; }
command -v openssl >/dev/null || { echo "openssl is required" >&2; exit 1; }

as_postgres() { runuser -u postgres -- psql --no-psqlrc --quiet --set ON_ERROR_STOP=1 "$@"; }
secret() { openssl rand -hex 32; }

install -d -m 700 -o root -g root "$env_dir"

# role -> env file that holds its password ("" = in no file)
declare -A role_file=(
    [ofa]=migrate [ofa_pipeline]=pipeline [ofa_web]=web [ofa_mailer]=mailer [ofa_backup]=backup
)
declare -A password=()

for role in ofa ofa_pipeline ofa_web ofa_mailer ofa_backup; do
    file=$env_dir/${role_file[$role]}.env
    exists=$(as_postgres --tuples-only --no-align \
        --command "SELECT 1 FROM pg_roles WHERE rolname = '$role'")
    if [ -z "$exists" ]; then
        as_postgres --command "CREATE ROLE $role NOLOGIN"
        echo "created role $role"
    fi
    if [ -e "$file" ]; then
        echo "$file exists: keeping the password of $role"
        continue
    fi
    password[$role]=$(secret)
    # The password goes over stdin, not the command line (no trace in ps or shell history).
    printf "ALTER ROLE %s LOGIN PASSWORD '%s';\n" "$role" "${password[$role]}" | as_postgres
    echo "set login password for $role"
done
as_postgres --command "GRANT pg_read_all_data TO ofa_backup"

if [ -z "$(as_postgres --tuples-only --no-align --command "SELECT 1 FROM pg_database WHERE datname = '$db'")" ]; then
    runuser -u postgres -- createdb --owner=ofa --encoding=UTF8 --template=template0 "$db"
    echo "created database $db"
fi
# Future-proof: nobody but the roles above may connect.
as_postgres --command "REVOKE CONNECT ON DATABASE $db FROM PUBLIC"
as_postgres --command "GRANT CONNECT ON DATABASE $db TO ofa, ofa_pipeline, ofa_web, ofa_mailer, ofa_backup"

# Shared subscription secrets: reuse whatever web.env or mailer.env already has.
read_key() { [ -r "$1" ] || return 0; sed -n "s/^$2=//p" "$1" | head -n 1; }
pepper='' token=''
for f in "$env_dir/web.env" "$env_dir/mailer.env"; do
    [ -n "$pepper" ] || pepper=$(read_key "$f" OFA_HASH_PEPPER)
    [ -n "$token" ] || token=$(read_key "$f" OFA_TOKEN_SECRET)
done
[ -n "$pepper" ] && [ "$pepper" != __SECRET__ ] || pepper=$(secret)
[ -n "$token" ] && [ "$token" != __SECRET__ ] || token=$(secret)

write_env() { # name role
    local name=$1 role=$2 file=$env_dir/$1.env tmp
    [ -e "$file" ] && return 0
    tmp=$(mktemp "$env_dir/.$name.XXXXXX")
    sed -e "s/__PASSWORD__/${password[$role]:-__PASSWORD__}/g" \
        -e "s/^OFA_HASH_PEPPER=__SECRET__$/OFA_HASH_PEPPER=$pepper/" \
        -e "s/^OFA_TOKEN_SECRET=__SECRET__$/OFA_TOKEN_SECRET=$token/" \
        "$templates/$name.env.example" >"$tmp"
    chown root:root "$tmp"
    chmod 600 "$tmp"
    mv "$tmp" "$file"
    echo "wrote $file"
}
write_env migrate ofa
write_env pipeline ofa_pipeline
write_env web ofa_web
write_env mailer ofa_mailer
write_env backup ofa_backup
[ -e "$env_dir/heartbeat.env" ] || install -m 600 -o root -g root \
    "$templates/heartbeat.env.example" "$env_dir/heartbeat.env"

if grep -l '__PASSWORD__\|__SECRET__' "$env_dir"/*.env >/dev/null 2>&1; then
    echo "WARNING: placeholders left in: $(grep -l '__PASSWORD__\|__SECRET__' "$env_dir"/*.env | xargs)" >&2
    echo "         (an env file existed while its role had no password set by this run)" >&2
fi
echo
echo "Done. Now fill in the API keys, BACKUP_AGE_RECIPIENTS and the rclone remote:"
echo "  sudoedit $env_dir/web.env $env_dir/mailer.env $env_dir/pipeline.env $env_dir/backup.env"
echo "Keep an offline copy of OFA_HASH_PEPPER and OFA_TOKEN_SECRET (password manager): a new"
echo "server needs the same values, or every manage link breaks and suppressions stop matching."
