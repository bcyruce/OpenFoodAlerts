"""Append-only archive of raw Source responses (ADR 0004).

A response is written only when its content differs from the latest archived response
for the same (Source, kind, source_key); rows are never updated or deleted.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from openfoodalerts.db.connection import Connection

Kind = Literal["list", "detail", "lookup", "sitemap"]


@dataclass(frozen=True)
class ArchiveOutcome:
    status: Literal["new", "changed", "unchanged"]
    raw_record_id: int


@dataclass(frozen=True)
class RawRecord:
    id: int
    source: str
    source_key: str
    kind: str
    url: str
    fetched_at: datetime
    http_status: int
    content_type: str
    body: bytes


def content_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def source_id(conn: Connection, source: str) -> int:
    row = conn.execute("SELECT id FROM sources WHERE code = %s", (source,)).fetchone()
    if row is None:
        raise KeyError(f"unknown source {source!r}")
    return int(row["id"])


def archive(
    conn: Connection,
    *,
    source: str,
    kind: Kind,
    source_key: str,
    url: str,
    http_status: int,
    content_type: str,
    body: bytes,
) -> ArchiveOutcome:
    sid = source_id(conn, source)
    digest = content_hash(body)
    latest = conn.execute(
        """
        SELECT id, content_hash FROM raw_records
        WHERE source_id = %s AND kind = %s AND source_key = %s
        ORDER BY id DESC LIMIT 1
        """,
        (sid, kind, source_key),
    ).fetchone()
    if latest is not None and latest["content_hash"] == digest:
        return ArchiveOutcome("unchanged", int(latest["id"]))
    row = conn.execute(
        """
        INSERT INTO raw_records
            (source_id, source_key, kind, url, http_status, content_hash, content_type, body)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (sid, source_key, kind, url, http_status, digest, content_type, body),
    ).fetchone()
    assert row is not None
    return ArchiveOutcome("new" if latest is None else "changed", int(row["id"]))


_RAW_COLUMNS = """
    r.id, s.code AS source, r.source_key, r.kind, r.url, r.fetched_at, r.http_status,
    r.content_type, r.body
"""


def _to_raw(row: dict[str, object]) -> RawRecord:
    return RawRecord(**{k: row[k] for k in RawRecord.__dataclass_fields__})  # type: ignore[arg-type]


def latest_raw(conn: Connection, *, source: str, kind: Kind, source_key: str) -> RawRecord | None:
    row = conn.execute(
        f"""
        SELECT {_RAW_COLUMNS} FROM raw_records r JOIN sources s ON s.id = r.source_id
        WHERE s.code = %s AND r.kind = %s AND r.source_key = %s
        ORDER BY r.id DESC LIMIT 1
        """,
        (source, kind, source_key),
    ).fetchone()
    return None if row is None else _to_raw(row)


def get_raw(conn: Connection, raw_record_id: int) -> RawRecord:
    row = conn.execute(
        f"SELECT {_RAW_COLUMNS} FROM raw_records r JOIN sources s ON s.id = r.source_id"
        " WHERE r.id = %s",
        (raw_record_id,),
    ).fetchone()
    if row is None:
        raise KeyError(raw_record_id)
    return _to_raw(row)
