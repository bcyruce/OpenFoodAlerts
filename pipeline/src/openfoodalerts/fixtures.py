"""`load-fixtures`: put fixture snapshots into the archive and parse them.

For local development and CI only (the web app's Playwright tests need Notifications to
show). A fixture file is a saved Source response; its Source is the name of the directory
it sits in (`.../openfda/page_recent.json`). Files are archived in the order given, so a
later snapshot of the same record becomes a new Notification version. Loading is
idempotent: a record whose exact content was archived before is skipped, even if a later
snapshot changed it since.
"""

import json
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from openfoodalerts.archive import archive, content_hash, source_id
from openfoodalerts.db.connection import Connection
from openfoodalerts.parse.run import parse


def _openfda_records(path: Path) -> Iterable[tuple[str, str, bytes]]:
    from openfoodalerts.sources.openfda.ingest import canonical_json
    from openfoodalerts.sources.openfda.parser import record_url

    body: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    for record in body.get("results", []):
        key = record["recall_number"]
        yield key, record_url(key), canonical_json(record)


_READERS = {"openfda": _openfda_records}


def _seen(conn: Connection, sid: int, key: str, body: bytes) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM raw_records
        WHERE source_id = %s AND kind = 'detail' AND source_key = %s AND content_hash = %s
        """,
        (sid, key, content_hash(body)),
    ).fetchone()
    return row is not None


def load_fixtures(conn: Connection, paths: Sequence[Path]) -> int:
    """Archive the records in `paths` and parse them; returns the number archived."""
    sources = [p.parent.name for p in paths]
    unsupported = sorted({s for s in sources if s not in _READERS})
    if unsupported:
        raise ValueError(f"no fixture reader for source(s): {', '.join(unsupported)}")
    archived = 0
    for path, source in zip(paths, sources, strict=True):
        sid = source_id(conn, source)
        for key, url, body in _READERS[source](path):
            if _seen(conn, sid, key, body):
                continue
            archive(
                conn,
                source=source,
                kind="detail",
                source_key=key,
                url=url,
                http_status=200,
                content_type="application/json",
                body=body,
            )
            archived += 1
        conn.commit()
    parse(conn, sorted(set(sources)))
    return archived
