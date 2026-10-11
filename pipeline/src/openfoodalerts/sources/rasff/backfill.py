"""`backfill-rasff`: walk every RASFF Window list page and fetch each missing detail.

Progress lives in `raw_records` (spec §5): a Notification whose detail is already archived
is skipped, and every detail is committed as soon as it is archived, so the job can be
stopped at any moment (Ctrl-C) and re-run to continue. Responses are archived exactly as
received, `additionalInformations` included (ADR 0004); the parser never reads it.

Archive keys: a detail is keyed by the RASFF `reference` (the Notification's source_key);
a list page by its canonical request body, prefixed with `consolidated:`. Pages shift as
new notifications arrive, so the same page key collects successive snapshots of that page.
"""

import json
from typing import Any

import httpx

from openfoodalerts.archive import archive
from openfoodalerts.db.connection import Connection
from openfoodalerts.jobs import JobStats, log_event, run_job
from openfoodalerts.sources.rasff.client import (
    ITEMS_PER_PAGE,
    RasffClient,
    detail_url,
    search_body,
    search_url,
)

SOURCE = "rasff"


class RasffFetchError(RuntimeError):
    """A list page could not be fetched."""


def list_page_key(body: dict[str, Any]) -> str:
    return "consolidated:" + json.dumps(body, sort_keys=True, separators=(",", ":"))


def archived_detail_keys(conn: Connection) -> set[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT r.source_key FROM raw_records r JOIN sources s ON s.id = r.source_id
        WHERE s.code = %s AND r.kind = 'detail'
        """,
        (SOURCE,),
    ).fetchall()
    return {r["source_key"] for r in rows}


def _content_type(response: httpx.Response) -> str:
    return str(response.headers.get("content-type", "application/json"))


def fetch_list_page(
    conn: Connection,
    client: RasffClient,
    page: int,
    items_per_page: int = ITEMS_PER_PAGE,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fetch and archive one list page; returns its parsed body."""
    body = search_body(page, items_per_page, filters)
    response = client.search(page, items_per_page, filters)
    if response.status_code != 200:
        raise RasffFetchError(f"list page {page}: HTTP {response.status_code}")
    archive(
        conn,
        source=SOURCE,
        kind="list",
        source_key=list_page_key(body),
        url=search_url(),
        http_status=response.status_code,
        content_type=_content_type(response),
        body=response.content,
    )
    conn.commit()
    payload: dict[str, Any] = response.json()
    return payload


def fetch_detail(
    conn: Connection, client: RasffClient, notif_id: int, reference: str, stats: JobStats
) -> bool:
    """Fetch and archive one detail; False when RASFF has no such detail."""
    response = client.detail(notif_id)
    if response.status_code == 404:
        log_event("rasff_detail_missing", notif_id=notif_id, reference=reference)
        stats.extra["missing"] = stats.extra.get("missing", 0) + 1
        return False
    if response.status_code != 200:
        raise RasffFetchError(f"detail {notif_id}: HTTP {response.status_code}")
    key = str(response.json().get("reference") or reference)
    if key != reference:
        log_event("rasff_reference_mismatch", notif_id=notif_id, list=reference, detail=key)
    outcome = archive(
        conn,
        source=SOURCE,
        kind="detail",
        source_key=key,
        url=detail_url(notif_id),
        http_status=response.status_code,
        content_type=_content_type(response),
        body=response.content,
    )
    conn.commit()
    stats.count(outcome.status)
    return True


def walk_list(
    conn: Connection,
    client: RasffClient,
    stats: JobStats,
    *,
    filters: dict[str, Any] | None = None,
    start_page: int = 1,
    max_pages: int | None = None,
    max_details: int | None = None,
    items_per_page: int = ITEMS_PER_PAGE,
) -> None:
    """Walk list pages from `start_page`; fetch the details not yet archived.

    Shared by `backfill-rasff` (whole list) and `ingest-rasff` (list filtered by date).
    Counts pages, skipped and fetched details in `stats.extra`.
    """
    stats.extra.update(pages=0, skipped=0, fetched=0, missing=0)
    archived = archived_detail_keys(conn)
    page = start_page
    while max_pages is None or stats.extra["pages"] < max_pages:
        payload = fetch_list_page(conn, client, page, items_per_page, filters)
        stats.extra["pages"] += 1
        stats.extra["total_pages"] = payload.get("totalPages")
        stats.extra["total_elements"] = payload.get("totalElements")
        items = payload.get("notifications") or []
        for item in items:
            reference = str(item["reference"])
            if reference in archived:
                stats.extra["skipped"] += 1
                continue
            if max_details is not None and stats.extra["fetched"] >= max_details:
                stats.extra["last_page"] = page
                stats.extra["capped"] = True
                return
            stats.extra["fetched"] += 1
            if fetch_detail(conn, client, int(item["notifId"]), reference, stats):
                archived.add(reference)
        stats.extra["last_page"] = page
        if not items or page >= int(payload.get("totalPages") or 0):
            break
        page += 1


def backfill_rasff(
    conn: Connection,
    client: RasffClient,
    *,
    start_page: int = 1,
    max_pages: int | None = None,
    max_details: int | None = None,
    items_per_page: int = ITEMS_PER_PAGE,
) -> JobStats:
    """Walk list pages from `start_page`; fetch details not yet archived.

    `max_pages` / `max_details` bound a run (small test runs); without them the whole list
    is walked.
    """
    with run_job(conn, "backfill-rasff", SOURCE, client.http) as stats:
        walk_list(
            conn,
            client,
            stats,
            start_page=start_page,
            max_pages=max_pages,
            max_details=max_details,
            items_per_page=items_per_page,
        )
    return stats
