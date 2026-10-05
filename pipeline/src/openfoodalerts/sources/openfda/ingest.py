"""`ingest-openfda`: full sync of openFDA food enforcement whenever its snapshot changes.

openFDA publishes weekly snapshots and edits old records, so each new snapshot is synced
in full with `search_after` paging (`skip` stops at 26,000 records) and every record is
archived on its own; the archive keeps only records whose content changed (ADR 0004).
"""

import json
import os
from typing import Any

import httpx

from openfoodalerts.archive import archive, latest_raw
from openfoodalerts.db.connection import Connection
from openfoodalerts.http import PoliteClient
from openfoodalerts.jobs import JobStats, run_job
from openfoodalerts.sources.openfda.parser import API_URL, record_url

PAGE_SIZE = 1000
META_KEY = "meta"


def canonical_json(value: Any) -> bytes:
    """Stable serialization, so unchanged records hash the same across snapshots."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def _with_key(params: dict[str, str]) -> dict[str, str]:
    key = os.environ.get("OPENFDA_API_KEY")
    return {**params, "api_key": key} if key else params


def _get(client: PoliteClient, url: str, params: dict[str, str] | None = None) -> httpx.Response:
    # Merge explicitly: the `Link: rel="next"` URL already carries search_after in its query.
    response = client.get(str(httpx.URL(url).copy_merge_params(_with_key(params or {}))))
    if response.status_code != 404:
        response.raise_for_status()
    return response


def _body(response: httpx.Response) -> dict[str, Any]:
    """404 means "no matches" in openFDA, so it is an empty page."""
    if response.status_code == 404:
        return {"meta": {}, "results": []}
    body: dict[str, Any] = response.json()
    return body


def _sync(conn: Connection, client: PoliteClient, stats: JobStats) -> int:
    seen = 0
    response = _get(client, API_URL, {"limit": str(PAGE_SIZE), "sort": "report_date:desc"})
    while True:
        for record in _body(response).get("results", []):
            outcome = archive(
                conn,
                source="openfda",
                kind="detail",
                source_key=record["recall_number"],
                url=record_url(record["recall_number"]),
                http_status=response.status_code,
                content_type="application/json",
                body=canonical_json(record),
            )
            stats.count(outcome.status)
            seen += 1
        conn.commit()
        next_url = response.links.get("next", {}).get("url")
        if response.status_code == 404 or not next_url:
            return seen
        response = _get(client, next_url)


def ingest_openfda(conn: Connection, client: PoliteClient) -> JobStats:
    with run_job(conn, "ingest-openfda", "openfda", client) as stats:
        probe = _get(client, API_URL, {"limit": "1"})
        meta = _body(probe).get("meta", {})
        last_updated = meta.get("last_updated")
        previous = latest_raw(conn, source="openfda", kind="list", source_key=META_KEY)
        if previous is not None and json.loads(previous.body).get("last_updated") == last_updated:
            stats.extra["synced"] = False
            return stats
        seen = _sync(conn, client, stats)
        stats.extra.update(
            synced=True,
            last_updated=last_updated,
            seen=seen,
            total=meta.get("results", {}).get("total"),
        )
        # Recorded only after a complete sync, so an interrupted sync is retried next run.
        archive(
            conn,
            source="openfda",
            kind="list",
            source_key=META_KEY,
            url=str(probe.request.url),
            http_status=probe.status_code,
            content_type="application/json",
            body=canonical_json(meta),
        )
    return stats
