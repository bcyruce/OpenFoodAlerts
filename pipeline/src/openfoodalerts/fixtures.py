"""`load-fixtures`: put fixture snapshots into the archive and parse them.

For local development and CI only (the web app's Playwright tests need Notifications to
show). A fixture file is a saved Source response; its Source is the nearest directory named
after one (`.../openfda/page_recent.json`, `.../rasff/details/881995.json`,
`.../nvwa/detail/cook-korianderzaad-update.html`):

- openfda: an API response page; every result is one record.
- rasff: one notification detail (JSON).
- nvwa: one detail page (HTML); its URL path comes from the page's canonical link. No
  search-result record is archived with it, so the Notification has no `source_ref`.

Files are archived in the order given, so a later snapshot of the same record becomes a new
Notification version. Loading is idempotent: a record whose exact content was archived
before is skipped, even if a later snapshot changed it since.
"""

import json
import re
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any, NamedTuple

from openfoodalerts.archive import archive, content_hash, source_id
from openfoodalerts.db.connection import Connection
from openfoodalerts.parse.run import parse


class FixtureRecord(NamedTuple):
    key: str
    url: str
    body: bytes
    content_type: str


def _openfda_records(path: Path) -> Iterable[FixtureRecord]:
    from openfoodalerts.sources.openfda.ingest import canonical_json
    from openfoodalerts.sources.openfda.parser import record_url

    body: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    for record in body.get("results", []):
        key = record["recall_number"]
        yield FixtureRecord(key, record_url(key), canonical_json(record), "application/json")


def _rasff_records(path: Path) -> Iterable[FixtureRecord]:
    from openfoodalerts.sources.rasff.parser import notification_page_url

    body = path.read_bytes()
    detail: dict[str, Any] = json.loads(body)
    yield FixtureRecord(
        detail["reference"], notification_page_url(detail["id"]), body, "application/json"
    )


_NVWA_CANONICAL = re.compile(rb'<link rel="canonical" href="https://www\.nvwa\.nl(/[^"?#]+)"')


def _nvwa_records(path: Path) -> Iterable[FixtureRecord]:
    body = path.read_bytes()
    match = _NVWA_CANONICAL.search(body)
    if match is None:
        raise ValueError(f"{path}: no canonical nvwa.nl link")
    key = match.group(1).decode()
    yield FixtureRecord(key, f"https://www.nvwa.nl{key}", body, "text/html; charset=utf-8")


_READERS: dict[str, Callable[[Path], Iterable[FixtureRecord]]] = {
    "openfda": _openfda_records,
    "rasff": _rasff_records,
    "nvwa": _nvwa_records,
}


def _source_of(path: Path) -> str:
    for parent in path.parents:
        if parent.name in _READERS:
            return parent.name
    raise ValueError(f"no fixture reader for {path}: no rasff/, nvwa/ or openfda/ directory")


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
    sources = [_source_of(p) for p in paths]
    archived = 0
    for path, source in zip(paths, sources, strict=True):
        sid = source_id(conn, source)
        for record in _READERS[source](path):
            if _seen(conn, sid, record.key, record.body):
                continue
            archive(
                conn,
                source=source,
                kind="detail",
                source_key=record.key,
                url=record.url,
                http_status=200,
                content_type=record.content_type,
                body=record.body,
            )
            archived += 1
        conn.commit()
    parse(conn, sorted(set(sources)))
    return archived
