"""Write parsed Notifications and their version history (spec §4.4).

Every observation of a Notification (one archived raw record) is compared with its current
normalized fields. A difference becomes a new row in `notification_versions` holding the
diff and whether the change is substantial. Times come from the raw record's `fetched_at`,
so replaying the archive reproduces the same history.
"""

from collections.abc import Callable
from typing import Any, Literal

from psycopg.types.json import Jsonb

from openfoodalerts.archive import RawRecord
from openfoodalerts.db.connection import Connection
from openfoodalerts.parse.model import ParsedNotification

FIELDS = tuple(ParsedNotification.model_fields)

# (previous, new) -> is the change substantial? One rule per Source (spec §10.3).
SubstantialRule = Callable[[ParsedNotification, ParsedNotification], bool]
Outcome = Literal["new", "changed", "unchanged"]


def never_substantial(old: ParsedNotification, new: ParsedNotification) -> bool:
    return False


def diff(old: ParsedNotification, new: ParsedNotification) -> dict[str, dict[str, Any]]:
    """Changed fields as {"field": {"old": ..., "new": ...}}; source_fields per key."""
    o, n = old.model_dump(mode="json"), new.model_dump(mode="json")
    changes: dict[str, dict[str, Any]] = {}
    for field in FIELDS:
        if field == "source_fields":
            for key in sorted(set(o[field]) | set(n[field])):
                before, after = o[field].get(key), n[field].get(key)
                if before != after:
                    changes[f"source_fields.{key}"] = {"old": before, "new": after}
        elif o[field] != n[field]:
            changes[field] = {"old": o[field], "new": n[field]}
    return changes


def _values(parsed: ParsedNotification) -> list[object]:
    return [Jsonb(v) if k == "source_fields" else v for k, v in parsed.model_dump().items()]


def _current(
    conn: Connection, source_id: int, source_key: str
) -> tuple[int, int, ParsedNotification] | None:
    row = conn.execute(
        f"""
        SELECT id, current_version, {", ".join(FIELDS)} FROM notifications
        WHERE source_id = %s AND source_key = %s
        """,
        (source_id, source_key),
    ).fetchone()
    if row is None:
        return None
    return int(row["id"]), int(row["current_version"]), ParsedNotification.model_validate(row)


def _insert_version(
    conn: Connection,
    notification_id: int,
    version: int,
    raw: RawRecord,
    changes: dict[str, dict[str, Any]],
    substantial: bool,
) -> None:
    conn.execute(
        """
        INSERT INTO notification_versions
            (notification_id, version, raw_record_id, observed_at, changed_fields, is_substantial)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (notification_id, version, raw.id, raw.fetched_at, Jsonb(changes), substantial),
    )


def _write_first(
    conn: Connection,
    source_id: int,
    parsed: ParsedNotification,
    raw: RawRecord,
    parser_version: str,
    existing_id: int | None,
) -> None:
    """Write version 1. A replay reuses the existing row so Notification ids stay stable."""
    if existing_id is None:
        row = conn.execute(
            f"""
            INSERT INTO notifications
                (source_id, {", ".join(FIELDS)}, raw_record_id, parser_version,
                 current_version, first_seen_at, last_changed_at)
            VALUES (%s, {", ".join(["%s"] * len(FIELDS))}, %s, %s, 1, %s, %s)
            RETURNING id
            """,
            [source_id, *_values(parsed), raw.id, parser_version, raw.fetched_at, raw.fetched_at],
        ).fetchone()
        assert row is not None
        notification_id = int(row["id"])
    else:
        notification_id = existing_id
        conn.execute(
            f"""
            UPDATE notifications SET {", ".join(f"{f} = %s" for f in FIELDS)},
                raw_record_id = %s, parser_version = %s, current_version = 1,
                first_seen_at = %s, last_changed_at = %s
            WHERE id = %s
            """,
            [*_values(parsed), raw.id, parser_version, raw.fetched_at, raw.fetched_at, existing_id],
        )
    _insert_version(conn, notification_id, 1, raw, {}, False)


def observe(
    conn: Connection,
    *,
    source_id: int,
    parsed: ParsedNotification,
    raw: RawRecord,
    parser_version: str,
    is_substantial: SubstantialRule = never_substantial,
) -> Outcome:
    """Record one observation of a Notification; returns what happened to it."""
    current = _current(conn, source_id, parsed.source_key)
    if current is None:
        _write_first(conn, source_id, parsed, raw, parser_version, None)
        return "new"
    notification_id, version, previous = current
    changes = diff(previous, parsed)
    if not changes:
        conn.execute(
            "UPDATE notifications SET raw_record_id = %s, parser_version = %s WHERE id = %s",
            (raw.id, parser_version, notification_id),
        )
        return "unchanged"
    version += 1
    _insert_version(conn, notification_id, version, raw, changes, is_substantial(previous, parsed))
    conn.execute(
        f"""
        UPDATE notifications SET {", ".join(f"{f} = %s" for f in FIELDS)},
            raw_record_id = %s, parser_version = %s, current_version = %s, last_changed_at = %s
        WHERE id = %s
        """,
        [*_values(parsed), raw.id, parser_version, version, raw.fetched_at, notification_id],
    )
    return "changed"


def reset_history(conn: Connection, source_id: int, source_key: str) -> int | None:
    """Drop a Notification's versions before a replay; returns its id if it exists."""
    row = conn.execute(
        "SELECT id FROM notifications WHERE source_id = %s AND source_key = %s",
        (source_id, source_key),
    ).fetchone()
    if row is None:
        return None
    conn.execute("DELETE FROM notification_versions WHERE notification_id = %s", (row["id"],))
    return int(row["id"])


def observe_first(
    conn: Connection,
    *,
    source_id: int,
    parsed: ParsedNotification,
    raw: RawRecord,
    parser_version: str,
    existing_id: int | None,
) -> None:
    """Replay: the earliest raw record becomes version 1 of an existing (or new) row."""
    _write_first(conn, source_id, parsed, raw, parser_version, existing_id)
