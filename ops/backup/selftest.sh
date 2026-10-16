#!/usr/bin/env bash
# selftest.sh: end-to-end test of backup.sh + restore.sh against a SCRATCH database (ticket 34).
#
#   PGHOST=... PGUSER=<superuser> PGPASSWORD=... ops/backup/selftest.sh ofa_drill_src
#
# The database must already be migrated (dbmate up) and its name must start with ofa_drill:
# the test writes subscriptions into it. Uses a throwaway age key and a local directory as
# the rclone remote, so no storage account is needed. It checks that:
#   1. backup.sh dump writes one encrypted dump + checksum, and nothing in plaintext;
#   2. restore.sh restores it into a new database with the same row count in every table;
#   3. the do-not-send ledger re-applies an unsubscribe and a "delete my data" made AFTER
#      the dump (docs/privacy/ropa.md §2.6);
#   4. pruning deletes old dumps but always keeps the BACKUP_KEEP_MIN newest;
#   5. restore.sh refuses an existing target and a tampered dump.
# This is the local restore drill recorded in implementation-log ### 34. On the server, the
# drill against real storage is `restore.sh --drill` (docs/runbook.md "Restore drill").
set -euo pipefail
export LC_ALL=C

src=${1:-}
case $src in ofa_drill*) ;; *) echo "usage: selftest.sh ofa_drill<name>  (scratch database only)" >&2; exit 2 ;; esac
here=$(dirname "$(readlink -f "$0")")
tmp=$(mktemp -d)
target="ofa_drill_restored_$$"
trap 'rm -rf "$tmp"; dropdb --if-exists "$target" 2>/dev/null || true; dropdb --if-exists "${target}_2" 2>/dev/null || true' EXIT

pass() { printf 'PASS  %s\n' "$*"; }
fail() { printf 'FAIL  %s\n' "$*"; exit 1; }
q() { psql --no-psqlrc --quiet --set ON_ERROR_STOP=1 --tuples-only --no-align --dbname="$1" --command "$2"; }

age-keygen -o "$tmp/key.txt" 2>/dev/null
recipient=$(age-keygen -y "$tmp/key.txt")
export BACKUP_AGE_RECIPIENTS=$recipient
export BACKUP_REMOTE=$tmp/remote
export BACKUP_WORK_DIR=$tmp
export BACKUP_DATABASE_URL="postgresql://${PGUSER}@${PGHOST:-localhost}:${PGPORT:-5432}/$src"
export BACKUP_KEEP_DAYS=30 BACKUP_KEEP_MIN=3
export RCLONE_CONFIG=${RCLONE_CONFIG:-/dev/null}
mkdir -p "$BACKUP_REMOTE"

# Two subscriptions that are active at dump time; both change after the dump.
q "$src" "DELETE FROM subscriptions WHERE email LIKE '%@drill.invalid'"
for i in 1 2; do
    q "$src" "INSERT INTO subscriptions (id, email, locale, filters, status, manage_token_hash,
        consent_at, consent_text_version, confirmed_at, email_hash)
      VALUES ('00000000-0000-4000-8000-00000000000$i', 'person$i@drill.invalid', 'en',
        '{\"sources\": []}', 'active', repeat('$i', 64), now(), 'drill', now(), repeat('$i', 64))"
done

"$here/backup.sh" dump
dumps() { find "$BACKUP_REMOTE/daily" -name 'ofa-*.dump.age' -printf '%f\n' | sort; }
n=$(dumps | wc -l)
sums=$(find "$BACKUP_REMOTE/daily" -name 'ofa-*.dump.age.sha256' | wc -l)
if [ "$n" -ne 1 ] || [ "$sums" -ne 1 ]; then fail "expected one dump and one checksum, found $n and $sums"; fi
grep -q -a 'PGDMP' "$BACKUP_REMOTE"/daily/ofa-*.dump.age && fail "dump is not encrypted"
head -c 40 "$BACKUP_REMOTE"/daily/ofa-*.dump.age | grep -q 'age-encryption.org/v1' || fail "not an age file"
[ -z "$(find "$tmp" -maxdepth 1 -name 'ofa-backup.*')" ] || fail "work directory left behind"
pass "dump encrypted and uploaded with checksum"

# After the dump: person1 unsubscribes, person2 deletes their data (suppression + delete).
q "$src" "UPDATE subscriptions SET status = 'unsubscribed', unsubscribed_at = now()
          WHERE id = '00000000-0000-4000-8000-000000000001'"
q "$src" "INSERT INTO email_suppressions (email_hash) VALUES (repeat('2', 64));
          DELETE FROM subscriptions WHERE id = '00000000-0000-4000-8000-000000000002'"
"$here/backup.sh" ledger
[ -s "$BACKUP_REMOTE/ledger/do-not-send.csv.age" ] || fail "no ledger"
pass "ledger written"

counts() {
    q "$1" "SELECT string_agg(t || '=' || n, ' ' ORDER BY t) FROM (
        SELECT table_name AS t,
               (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM public.%I', table_name),
                                                     false, true, '')))[1]::text AS n
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE') x"
}
expected=$(counts "$src")

"$here/restore.sh" --identity "$tmp/key.txt" --target "$target" --owner "$PGUSER" --ledger latest
# The source changed after the dump only in the two drill rows; compare everything else.
got=$(counts "$target")
strip() { tr ' ' '\n' <<<"$1" | grep -v -E '^(subscriptions|email_suppressions|email_deliveries)=' | xargs; }
[ "$(strip "$got")" = "$(strip "$expected")" ] || fail "row counts differ:
  source:   $(strip "$expected")
  restored: $(strip "$got")"
pass "restored row counts match ($(tr ' ' '\n' <<<"$got" | wc -l) tables)"

s1=$(q "$target" "SELECT status FROM subscriptions WHERE id = '00000000-0000-4000-8000-000000000001'")
s2=$(q "$target" "SELECT count(*) FROM subscriptions WHERE id = '00000000-0000-4000-8000-000000000002'")
sup=$(q "$target" "SELECT count(*) FROM email_suppressions WHERE email_hash = repeat('2', 64)")
send=$(q "$target" "SELECT count(*) FROM sendable_subscriptions WHERE email LIKE '%@drill.invalid'")
[ "$s1" = unsubscribed ] || fail "unsubscribe after the dump was not re-applied (status $s1)"
if [ "$s2" != 0 ] || [ "$sup" != 1 ]; then
    fail "deletion after the dump was not re-applied ($s2 rows, $sup suppressions)"
fi
[ "$send" = 0 ] || fail "$send drill subscriptions still sendable"
pass "do-not-send ledger re-applied (unsubscribe kept, deleted data stays deleted)"

if "$here/restore.sh" --identity "$tmp/key.txt" --target "$target" --owner "$PGUSER" latest 2>/dev/null; then
    fail "restore into an existing database was not refused"
fi
pass "existing target refused"

# Tampered dump: flip bytes in a copy, point its checksum at the original.
dump=$(dumps | head -n 1)
bad=ofa-29991231T000000Z.dump.age
cp "$BACKUP_REMOTE/daily/$dump" "$BACKUP_REMOTE/daily/$bad"
printf 'XXXX' | dd of="$BACKUP_REMOTE/daily/$bad" bs=1 seek=200 conv=notrunc status=none
sed "s/$dump/$bad/" "$BACKUP_REMOTE/daily/$dump.sha256" >"$BACKUP_REMOTE/daily/$bad.sha256"
if "$here/restore.sh" --identity "$tmp/key.txt" --target "${target}_2" --owner "$PGUSER" "$bad" 2>/dev/null; then
    fail "tampered dump was restored"
fi
rm "$BACKUP_REMOTE/daily/$bad" "$BACKUP_REMOTE/daily/$bad.sha256"
pass "tampered dump refused"

# Pruning: ten fake dumps from 2020 plus the real ones; KEEP_MIN=3.
for d in 01 02 03 04 05 06 07 08 09 10; do
    : >"$BACKUP_REMOTE/daily/ofa-202001${d}T000000Z.dump.age"
done
sleep 1
"$here/backup.sh" dump
left=$(dumps | xargs)
n=$(wc -w <<<"$left")
[ "$n" -eq 3 ] || fail "expected 3 dumps after pruning, got $n: $left"
case $left in "ofa-20200110T000000Z.dump.age "*) ;; *) fail "pruning removed the wrong files: $left" ;; esac
BACKUP_KEEP_DAYS=0 "$here/backup.sh" dump
n=$(dumps | wc -l)
[ "$n" -eq 4 ] || fail "BACKUP_KEEP_DAYS=0 should not prune (got $n dumps)"
pass "pruning keeps the newest BACKUP_KEEP_MIN and honours BACKUP_KEEP_DAYS=0"

"$here/restore.sh" --identity "$tmp/key.txt" --target "${target}_2" --owner "$PGUSER" --drill latest
pass "restore.sh --drill"

q "$src" "DELETE FROM subscriptions WHERE email LIKE '%@drill.invalid';
          DELETE FROM email_suppressions WHERE email_hash = repeat('2', 64)"
echo "all backup/restore checks passed"
