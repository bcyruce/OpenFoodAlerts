"""Write parsed Notifications and their version history (spec §4.4).

Every observation of a Notification (one archived raw record) is compared with its current
normalized fields. A difference becomes a new row in `notification_versions` holding the
diff and whether the change is substantial. Times come from the raw record's `fetched_at`,
so replaying the archive reproduces the same history.

Official child records (Hazards, Product categories, countries with roles, measures) are part
of the observed state: they are compared like any other field and, when anything changed,
replaced as a whole. AI-made child rows (provenance = 'ai') are left alone, and so is a
Product type set by T5 (provenance 'ai') while the rules still cannot decide: it is
compared as `pending` (T5 is not a change of the source) and kept on writes
(`_keep_ai_product_type`); a rule decision replaces it.

Whenever the stored state changes, `search_tsv` is rebuilt from it by the SQL function
`notification_search_tsv` (migration 20261025000800_search, which also backfilled the rows
that existed before it).
"""

from collections.abc import Callable
from typing import Any, Literal

from psycopg.types.json import Jsonb

from openfoodalerts.archive import RawRecord
from openfoodalerts.db.connection import Connection
from openfoodalerts.parse.model import CHILD_FIELDS, ParsedNotification

# Every compared field; COLUMNS are the ones stored in `notifications` itself.
FIELDS = tuple(ParsedNotification.model_fields)
COLUMNS = tuple(f for f in FIELDS if f not in CHILD_FIELDS)

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
    dumped = parsed.model_dump(include=set(COLUMNS))
    return [Jsonb(dumped[k]) if k == "source_fields" else dumped[k] for k in COLUMNS]


_LOAD_CHILDREN = {
    "hazards": """
        SELECT h.hazard_name AS name, c.rasff_id AS category_rasff_id, h.is_primary,
               h.analytical_result, h.unit, h.max_permitted_level, h.sampling_date,
               h.provenance
        FROM notification_hazards h LEFT JOIN hazard_categories c ON c.id = h.hazard_category_id
        WHERE h.notification_id = %s AND h.provenance = 'official' ORDER BY h.position, h.id
    """,
    "product_categories": """
        SELECT p.rasff_id, x.provenance
        FROM notification_product_categories x
        JOIN product_categories p ON p.id = x.product_category_id
        WHERE x.notification_id = %s AND x.provenance = 'official' ORDER BY x.position, x.id
    """,
    "countries": """
        SELECT country_iso2 AS iso2, role, provenance FROM notification_countries
        WHERE notification_id = %s AND provenance = 'official'
    """,
    "measures": """
        SELECT country_iso2, action_rasff_id, action_text FROM measures
        WHERE notification_id = %s ORDER BY position, id
    """,
}


_CHILD_TABLES_WITH_PROVENANCE = (
    "notification_hazards",
    "notification_product_categories",
    "notification_countries",
)


def _load_children(conn: Connection, notification_id: int) -> dict[str, list[dict[str, Any]]]:
    return {
        name: conn.execute(sql, (notification_id,)).fetchall()
        for name, sql in _LOAD_CHILDREN.items()
    }


def _write_children(conn: Connection, notification_id: int, parsed: ParsedNotification) -> None:
    """Replace the official child records of one Notification with the parsed ones."""
    nid = notification_id
    for table in _CHILD_TABLES_WITH_PROVENANCE:
        conn.execute(
            f"DELETE FROM {table} WHERE notification_id = %s AND provenance = 'official'", (nid,)
        )
    conn.execute("DELETE FROM measures WHERE notification_id = %s", (nid,))
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO notification_hazards
                (notification_id, position, hazard_name, hazard_category_id, is_primary,
                 analytical_result, unit, max_permitted_level, sampling_date, provenance)
            VALUES (%s, %s, %s, (SELECT id FROM hazard_categories WHERE rasff_id = %s),
                    %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    nid,
                    i,
                    h.name,
                    h.category_rasff_id,
                    h.is_primary,
                    h.analytical_result,
                    h.unit,
                    h.max_permitted_level,
                    h.sampling_date,
                    h.provenance,
                )
                for i, h in enumerate(parsed.hazards)
            ],
        )
        cur.executemany(
            """
            INSERT INTO notification_product_categories
                (notification_id, position, product_category_id, provenance)
            VALUES (%s, %s, (SELECT id FROM product_categories WHERE rasff_id = %s), %s)
            """,
            [(nid, i, c.rasff_id, c.provenance) for i, c in enumerate(parsed.product_categories)],
        )
        cur.executemany(
            """
            INSERT INTO notification_countries (notification_id, country_iso2, role, provenance)
            VALUES (%s, %s, %s, %s)
            """,
            [(nid, c.iso2, c.role, c.provenance) for c in parsed.countries],
        )
        cur.executemany(
            """
            INSERT INTO measures (notification_id, position, country_iso2, action_rasff_id,
                                  action_text)
            VALUES (%s, %s, %s, %s, %s)
            """,
            [
                (nid, i, m.country_iso2, m.action_rasff_id, m.action_text)
                for i, m in enumerate(parsed.measures)
            ],
        )


def _write_search_document(conn: Connection, notification_id: int) -> None:
    conn.execute(
        "UPDATE notifications SET search_tsv = notification_search_tsv(id) WHERE id = %s",
        (notification_id,),
    )


def _keep_ai_product_type(parsed: ParsedNotification, ai_type: str | None) -> ParsedNotification:
    """A Product type set by T5 (provenance ai) belongs to the classifier: it stays while
    the rules still cannot decide (the parser says `pending`); a rule decision replaces it."""
    if ai_type is None or parsed.product_type_provenance != "pending":
        return parsed
    return parsed.model_copy(update={"product_type": ai_type, "product_type_provenance": "ai"})


def _current(
    conn: Connection, source_id: int, source_key: str
) -> tuple[int, int, ParsedNotification, str | None] | None:
    """(id, version, the stored state as the parser saw it, T5's Product type or None)."""
    row = conn.execute(
        f"""
        SELECT id, current_version, {", ".join(COLUMNS)} FROM notifications
        WHERE source_id = %s AND source_key = %s
        """,
        (source_id, source_key),
    ).fetchone()
    if row is None:
        return None
    notification_id = int(row["id"])
    ai_type = row["product_type"] if row["product_type_provenance"] == "ai" else None
    if ai_type is not None:  # compare with what the parser wrote: T5 is not a source change
        row |= {"product_type": None, "product_type_provenance": "pending"}
    state = ParsedNotification.model_validate({**row, **_load_children(conn, notification_id)})
    return notification_id, int(row["current_version"]), state, ai_type


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
                (source_id, {", ".join(COLUMNS)}, raw_record_id, parser_version,
                 current_version, first_seen_at, last_changed_at)
            VALUES (%s, {", ".join(["%s"] * len(COLUMNS))}, %s, %s, 1, %s, %s)
            RETURNING id
            """,
            [source_id, *_values(parsed), raw.id, parser_version, raw.fetched_at, raw.fetched_at],
        ).fetchone()
        assert row is not None
        notification_id = int(row["id"])
    else:
        notification_id = existing_id
        kept = conn.execute(
            "SELECT product_type FROM notifications WHERE id = %s"
            " AND product_type_provenance = 'ai'",
            (existing_id,),
        ).fetchone()
        parsed = _keep_ai_product_type(parsed, kept["product_type"] if kept else None)
        conn.execute(
            f"""
            UPDATE notifications SET {", ".join(f"{f} = %s" for f in COLUMNS)},
                raw_record_id = %s, parser_version = %s, current_version = 1,
                first_seen_at = %s, last_changed_at = %s
            WHERE id = %s
            """,
            [*_values(parsed), raw.id, parser_version, raw.fetched_at, raw.fetched_at, existing_id],
        )
    _write_children(conn, notification_id, parsed)
    _write_search_document(conn, notification_id)
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
    notification_id, version, previous, ai_type = current
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
        UPDATE notifications SET {", ".join(f"{f} = %s" for f in COLUMNS)},
            raw_record_id = %s, parser_version = %s, current_version = %s, last_changed_at = %s
        WHERE id = %s
        """,
        [
            *_values(_keep_ai_product_type(parsed, ai_type)),
            raw.id,
            parser_version,
            version,
            raw.fetched_at,
            notification_id,
        ],
    )
    if any(field in changes for field in CHILD_FIELDS):
        _write_children(conn, notification_id, parsed)
    _write_search_document(conn, notification_id)
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
