"""`backfill-nvwa` and `ingest-nvwa`: archive NVWA safety warnings (spec §3.2, §5).

Each search result is archived on its own (kind `list`, source_key = URL path), like the
openFDA records: the parser takes the Elastic id from it, and the volatile request id of
the page response stays out of the archive. Detail pages are archived as served (kind
`detail`). Sitemap pages are archived as served (kind `sitemap`, source_key
`/sitemap/N.xml`); the previous archived copy is the "last observed lastmod" of every URL
on it, so no extra state table is needed (ADR 0004).
"""

import json
from dataclasses import dataclass
from datetime import datetime

import httpx

from openfoodalerts.archive import archive, latest_raw, source_id
from openfoodalerts.db.connection import Connection
from openfoodalerts.http import PoliteClient
from openfoodalerts.jobs import JobStats, run_job
from openfoodalerts.sources.nvwa import api

SOURCE = "nvwa"
SITEMAP_PAGES = (1, 2)
MIN_INTERVAL = 2.0  # seconds between requests (spec §5)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def _archive_item(conn: Connection, item: api.ListItem) -> None:
    archive(
        conn,
        source=SOURCE,
        kind="list",
        source_key=item.path,
        url=api.SEARCH_URL,
        http_status=200,
        content_type="application/json",
        body=_canonical(item.raw),
    )


def _known_details(conn: Connection) -> set[str]:
    rows = conn.execute(
        "SELECT DISTINCT source_key FROM raw_records WHERE source_id = %s AND kind = 'detail'",
        (source_id(conn, SOURCE),),
    ).fetchall()
    return {r["source_key"] for r in rows}


def _fetch_detail(conn: Connection, client: PoliteClient, path: str, stats: JobStats) -> None:
    response = client.get(api.detail_url(path))
    if response.status_code == 404:
        stats.extra["missing"] = [*stats.extra.get("missing", []), path]
        return
    response.raise_for_status()
    outcome = archive(
        conn,
        source=SOURCE,
        kind="detail",
        source_key=path,
        url=api.detail_url(path),
        http_status=response.status_code,
        content_type=response.headers.get("Content-Type", "text/html"),
        body=response.content,
    )
    stats.count(outcome.status)
    conn.commit()


def _list_all(
    conn: Connection, client: PoliteClient, per_page: int, stats: JobStats
) -> list[api.ListItem]:
    items: list[api.ListItem] = []
    total = 0
    for content_type in api.CONTENT_TYPES:
        page_number, pages = 1, 1
        while page_number <= pages:
            page = api.fetch_page(client, content_type, page_number, per_page)
            pages = page.total_pages
            for item in page.items:
                _archive_item(conn, item)
            items.extend(page.items)
            conn.commit()
            page_number += 1
        total += page.total_results
    stats.extra.update(total_results=total, listed=len({i.path for i in items}))
    return items


def backfill_nvwa(
    conn: Connection, client: PoliteClient, *, per_page: int = api.PAGE_SIZE
) -> JobStats:
    """List every warning (new list and archive), then fetch each detail not yet archived.

    Progress lives in the archive: an interrupted run continues where it stopped.
    """
    with run_job(conn, "backfill-nvwa", SOURCE, client) as stats:
        items = _list_all(conn, client, per_page, stats)
        known = _known_details(conn)
        stats.extra["skipped"] = 0
        for item in items:
            if item.path in known:
                stats.extra["skipped"] += 1
                continue
            _fetch_detail(conn, client, item.path, stats)
            known.add(item.path)
    return stats


def _new_from_api(conn: Connection, client: PoliteClient, stats: JobStats) -> None:
    """Newest first: page through the new list until a page contains a known warning.

    Every unknown item on that page is fetched, not just those above the first known one,
    because a late publication can carry an older sort_date.
    """
    known = _known_details(conn)
    new = 0
    page_number, pages = 1, 1
    while page_number <= pages:
        page = api.fetch_page(client, api.NEWS, page_number)
        pages = page.total_pages
        unknown = [i for i in page.items if i.path not in known]
        for item in page.items:
            _archive_item(conn, item)
        for item in unknown:
            _fetch_detail(conn, client, item.path, stats)
            known.add(item.path)
        conn.commit()
        new += len(unknown)
        if len(unknown) < len(page.items):
            break
        page_number += 1
    stats.extra["new_warnings"] = new


def _last_fetched(conn: Connection, path: str) -> datetime | None:
    raw = latest_raw(conn, source=SOURCE, kind="detail", source_key=path)
    return None if raw is None else raw.fetched_at


@dataclass(frozen=True)
class _SitemapPage:
    number: int
    response: httpx.Response

    @property
    def key(self) -> str:
        return f"/sitemap/{self.number}.xml"


def _refresh_from_sitemap(conn: Connection, client: PoliteClient, stats: JobStats) -> None:
    """Refetch known warnings whose sitemap lastmod is later than the last one observed.

    "Last observed" is the lastmod in the previously archived copy of the sitemap pages;
    for a URL not on them, the time its detail was last fetched.
    """
    known = _known_details(conn)
    previous: dict[str, datetime] = {}
    current: dict[str, datetime] = {}
    pages = []
    for number in SITEMAP_PAGES:
        page = _SitemapPage(number, client.get(api.sitemap_url(number)))
        page.response.raise_for_status()
        archived = latest_raw(conn, source=SOURCE, kind="sitemap", source_key=page.key)
        if archived is not None:
            previous.update(api.parse_sitemap(archived.body))
        current.update(api.parse_sitemap(page.response.content))
        pages.append(page)
    refetched = 0
    for path, lastmod in current.items():
        if path not in known:
            continue
        seen = previous.get(path) or _last_fetched(conn, path)
        if seen is not None and lastmod <= seen:
            continue
        _fetch_detail(conn, client, path, stats)
        refetched += 1
    # Archived last: if a refetch fails, the next run compares against the old copy again.
    for page in pages:
        archive(
            conn,
            source=SOURCE,
            kind="sitemap",
            source_key=page.key,
            url=api.sitemap_url(page.number),
            http_status=page.response.status_code,
            content_type=page.response.headers.get("Content-Type", "application/xml"),
            body=page.response.content,
        )
    stats.extra["refetched"] = refetched


def ingest_nvwa(conn: Connection, client: PoliteClient) -> JobStats:
    """Every 2 hours: new warnings from the API, then updates detected via the sitemap."""
    with run_job(conn, "ingest-nvwa", SOURCE, client) as stats:
        _new_from_api(conn, client, stats)
        _refresh_from_sitemap(conn, client, stats)
    return stats
