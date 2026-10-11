"""`parse` and `replay`: turn archived raw records into Notifications and their versions.

`parse` is incremental and idempotent per (raw_record_id, parser_version): it applies raw
records newer than the one each Notification was last built from. When a Source's parser
version changed, the affected Notifications are replayed: their history is rebuilt from
the archive, never refetched (ADR 0004). `replay` does that for every Notification.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from openfoodalerts.archive import RawRecord, get_raw, source_id
from openfoodalerts.db.connection import Connection
from openfoodalerts.jobs import JobStats, run_job
from openfoodalerts.parse.model import ParsedNotification
from openfoodalerts.parse.store import (
    SubstantialRule,
    never_substantial,
    observe,
    observe_first,
    reset_history,
)

BATCH = 500


@dataclass(frozen=True)
class SourceParser:
    source: str
    version: str
    parse: Callable[[Connection, RawRecord], ParsedNotification | None]
    is_substantial: SubstantialRule = field(default=never_substantial)


def _registry() -> dict[str, SourceParser]:
    from openfoodalerts.sources.nvwa.parser import PARSER as NVWA
    from openfoodalerts.sources.openfda.parser import PARSER as OPENFDA

    return {p.source: p for p in (OPENFDA, NVWA)}


def _apply(conn: Connection, parser: SourceParser, sid: int, raw_id: int, stats: JobStats) -> None:
    raw = get_raw(conn, raw_id)
    parsed = parser.parse(conn, raw)
    if parsed is None:
        return
    stats.count(
        observe(
            conn,
            source_id=sid,
            parsed=parsed,
            raw=raw,
            parser_version=parser.version,
            is_substantial=parser.is_substantial,
        )
    )


def rebuild(conn: Connection, parser: SourceParser, sid: int, source_key: str) -> None:
    """Rebuild one Notification's state and versions from all of its archived raw records."""
    raw_ids = [
        int(r["id"])
        for r in conn.execute(
            """
            SELECT id FROM raw_records
            WHERE source_id = %s AND kind = 'detail' AND source_key = %s ORDER BY id
            """,
            (sid, source_key),
        ).fetchall()
    ]
    existing_id = reset_history(conn, sid, source_key)
    started = False
    scratch = JobStats(job="replay", source=parser.source)
    for raw_id in raw_ids:
        if started:
            _apply(conn, parser, sid, raw_id, scratch)
            continue
        raw = get_raw(conn, raw_id)
        parsed = parser.parse(conn, raw)
        if parsed is None:
            continue
        observe_first(
            conn,
            source_id=sid,
            parsed=parsed,
            raw=raw,
            parser_version=parser.version,
            existing_id=existing_id,
        )
        started = True


def _commit_every(conn: Connection, i: int) -> None:
    if i % BATCH == 0:
        conn.commit()


def parse_source(conn: Connection, parser: SourceParser, stats: JobStats) -> None:
    sid = source_id(conn, parser.source)
    outdated = conn.execute(
        "SELECT source_key FROM notifications WHERE source_id = %s AND parser_version <> %s",
        (sid, parser.version),
    ).fetchall()
    for i, row in enumerate(outdated, start=1):
        rebuild(conn, parser, sid, row["source_key"])
        stats.extra["replayed"] = stats.extra.get("replayed", 0) + 1
        _commit_every(conn, i)
    pending = conn.execute(
        """
        SELECT r.id FROM raw_records r
        LEFT JOIN notifications n ON n.source_id = r.source_id AND n.source_key = r.source_key
        WHERE r.source_id = %s AND r.kind = 'detail' AND (n.id IS NULL OR r.id > n.raw_record_id)
        ORDER BY r.id
        """,
        (sid,),
    ).fetchall()
    for i, row in enumerate(pending, start=1):
        _apply(conn, parser, sid, int(row["id"]), stats)
        _commit_every(conn, i)
    conn.commit()


def replay_source(conn: Connection, parser: SourceParser, stats: JobStats) -> None:
    sid = source_id(conn, parser.source)
    keys = conn.execute(
        """
        SELECT DISTINCT source_key FROM raw_records
        WHERE source_id = %s AND kind = 'detail' ORDER BY source_key
        """,
        (sid,),
    ).fetchall()
    for i, row in enumerate(keys, start=1):
        rebuild(conn, parser, sid, row["source_key"])
        stats.extra["replayed"] = stats.extra.get("replayed", 0) + 1
        _commit_every(conn, i)
    conn.commit()


def parse(conn: Connection, sources: Iterable[str] | None = None) -> JobStats:
    registry = _registry()
    with run_job(conn, "parse", None) as stats:
        for code in sources or registry:
            parse_source(conn, registry[code], stats)
    return stats


def replay(conn: Connection, sources: Iterable[str] | None = None) -> JobStats:
    """Re-parse the whole archive with the current parsers; makes no network requests."""
    registry = _registry()
    with run_job(conn, "replay", None) as stats:
        for code in sources or registry:
            replay_source(conn, registry[code], stats)
    return stats
