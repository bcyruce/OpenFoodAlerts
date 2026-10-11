"""backfill-nvwa and ingest-nvwa against a fake NVWA website (spec §3.2, §5)."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from openfoodalerts.db.connection import Connection
from openfoodalerts.http import PoliteClient
from openfoodalerts.sources.nvwa import api
from openfoodalerts.sources.nvwa.ingest import backfill_nvwa, ingest_nvwa

POKEBOWL = "/actueel/nieuws/2026/10/24/veiligheidswaarschuwing-ah-pokebowl-sticky-tempeh-allergenen"
PUDDING = "/actueel/nieuws/2026/10/23/veiligheidswaarschuwing-melkunie-protein-pudding"


class FakeNVWA:
    """Serves the search API, detail pages and sitemap pages the way www.nvwa.nl does."""

    def __init__(self, fixtures: Path) -> None:
        def results(name: str) -> list[dict[str, Any]]:
            payload = json.loads((fixtures / "nvwa" / name).read_text(encoding="utf-8"))
            items: list[dict[str, Any]] = payload["results"]
            return items

        self.items = {
            api.NEWS: results("list_news_p1.json"),
            api.ARCHIVE: results("list_archive_p6.json"),
        }
        self.html: dict[str, str] = {}
        self.sitemaps: dict[int, str] = {}
        self.requests: list[httpx.Request] = []
        self.fail_detail_after: int | None = None
        self.detail_requests = 0
        self.gone: set[str] = set()

    def page_html(self, path: str) -> str:
        return self.html.get(
            path,
            f"<html><head><meta name='DCTERMS.modified' content='2026-10-01T10:00:00Z'></head>"
            f"<body><main><h1>Veiligheidswaarschuwing {path}</h1>"
            f"<div class='intro'><div class='rich-text'><p>Eet het product niet.</p></div></div>"
            f"</main></body></html>",
        )

    def search(self, request: httpx.Request) -> httpx.Response:
        assert request.url.params["hash"] == hashlib.sha256(request.content).hexdigest()
        state = json.loads(request.content)["requestState"]
        [content_type] = next(f["values"] for f in state["filters"] if f["field"] == "content_type")
        items = self.items[content_type]
        size, current = state["resultsPerPage"], state["current"]
        total_pages = max(1, -(-len(items) // size))
        page = items[(current - 1) * size : current * size]
        return httpx.Response(
            200,
            json={
                "results": page,
                "totalResults": len(items),
                "totalPages": total_pages,
                "requestId": f"r{len(self.requests)}",
            },
        )

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/api/search":
            return self.search(request)
        if path.startswith("/sitemap/"):
            page = int(path.removeprefix("/sitemap/").removesuffix(".xml"))
            return httpx.Response(200, text=self.sitemaps.get(page, "<urlset/>"))
        self.detail_requests += 1
        if self.fail_detail_after is not None and self.detail_requests > self.fail_detail_after:
            raise httpx.ConnectError("connection reset")
        if path in self.gone:
            return httpx.Response(404, text="Niet gevonden")
        return httpx.Response(200, text=self.page_html(path), headers={"Content-Type": "text/html"})

    def client(self) -> PoliteClient:
        return PoliteClient(transport=httpx.MockTransport(self.handler), sleep=lambda s: None)

    def add_news(self, path: str, item_id: str) -> None:
        item = json.loads(json.dumps(self.items[api.NEWS][0]))
        item["url"]["raw"], item["id"]["raw"] = path, item_id
        self.items[api.NEWS].insert(0, item)

    def detail_paths_requested(self) -> list[str]:
        return [
            r.url.path
            for r in self.requests
            if r.url.path != "/api/search" and not r.url.path.startswith("/sitemap/")
        ]


def keys(db: Connection, kind: str) -> set[str]:
    rows = db.execute(
        "SELECT DISTINCT source_key FROM raw_records r JOIN sources s ON s.id = r.source_id"
        " WHERE s.code = 'nvwa' AND r.kind = %s",
        (kind,),
    ).fetchall()
    return {r["source_key"] for r in rows}


@pytest.fixture
def nvwa(fixtures_dir: Path) -> FakeNVWA:
    return FakeNVWA(fixtures_dir)


def all_paths(nvwa: FakeNVWA) -> set[str]:
    return {i["url"]["raw"] for items in nvwa.items.values() for i in items}


def test_backfill_lists_both_content_types_and_archives_every_detail(
    db: Connection, nvwa: FakeNVWA
) -> None:
    stats = backfill_nvwa(db, nvwa.client(), per_page=50)
    assert keys(db, "detail") == all_paths(nvwa)
    assert len(all_paths(nvwa)) == 70
    assert keys(db, "list") == all_paths(nvwa)
    assert stats.extra["total_results"] == 70
    assert stats.extra["listed"] == 70
    assert stats.new == 70
    searches = [r for r in nvwa.requests if r.url.path == "/api/search"]
    assert len(searches) == 3  # news in two pages of 50, archive in one


def test_backfill_resumes_after_interruption_without_refetching(
    db: Connection, nvwa: FakeNVWA
) -> None:
    nvwa.fail_detail_after = 30
    with pytest.raises(httpx.ConnectError):
        backfill_nvwa(db, nvwa.client(), per_page=50)
    done = keys(db, "detail")
    assert len(done) == 30
    nvwa.fail_detail_after = None
    nvwa.requests.clear()
    backfill_nvwa(db, nvwa.client(), per_page=50)
    assert keys(db, "detail") == all_paths(nvwa)
    refetched = set(nvwa.detail_paths_requested())
    assert refetched == all_paths(nvwa) - done


def test_a_listed_page_that_is_gone_is_reported_not_archived(
    db: Connection, nvwa: FakeNVWA
) -> None:
    nvwa.gone = {PUDDING}
    stats = backfill_nvwa(db, nvwa.client())
    assert stats.extra["missing"] == [PUDDING]
    assert PUDDING not in keys(db, "detail")
    assert len(keys(db, "detail")) == 69


def sitemap(entries: dict[str, str]) -> str:
    urls = "".join(
        f"<url><loc>https://www.nvwa.nl{p}</loc><lastmod>{m}</lastmod></url>"
        for p, m in entries.items()
    )
    return f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'


def test_ingest_fetches_new_warnings_from_page_one_and_stops_at_known(
    db: Connection, nvwa: FakeNVWA
) -> None:
    backfill_nvwa(db, nvwa.client())
    nvwa.add_news("/actueel/nieuws/2026/10/25/veiligheidswaarschuwing-nieuw", "doc-new")
    nvwa.requests.clear()
    stats = ingest_nvwa(db, nvwa.client())
    assert nvwa.detail_paths_requested() == [
        "/actueel/nieuws/2026/10/25/veiligheidswaarschuwing-nieuw"
    ]
    searches = [json.loads(r.content) for r in nvwa.requests if r.url.path == "/api/search"]
    assert [s["requestState"]["current"] for s in searches] == [1]
    assert searches[0]["requestState"]["filters"][1]["values"] == [api.NEWS]
    assert stats.extra["new_warnings"] == 1


def test_ingest_refetches_known_pages_whose_sitemap_lastmod_moved_on(
    db: Connection, nvwa: FakeNVWA
) -> None:
    backfill_nvwa(db, nvwa.client())
    # Before the first ingest run the archive has no sitemap; lastmod older than the fetch
    # means the archived detail is current.
    nvwa.sitemaps = {1: sitemap({POKEBOWL: "2026-10-24T14:46:09.586Z", "/over-ons": "2030-01-01"})}
    nvwa.requests.clear()
    ingest_nvwa(db, nvwa.client())
    assert nvwa.detail_paths_requested() == []

    nvwa.sitemaps = {
        1: sitemap({POKEBOWL: "2026-10-24T14:46:09.586Z"}),
        2: sitemap({PUDDING: _future()}),
    }
    nvwa.html[PUDDING] = nvwa.page_html(PUDDING).replace("Eet", "Update 25 oktober 2026: x. Eet")
    nvwa.requests.clear()
    stats = ingest_nvwa(db, nvwa.client())
    assert nvwa.detail_paths_requested() == [PUDDING]
    assert stats.extra["refetched"] == 1
    assert stats.changed == 1

    # The same lastmod again: already observed, nothing to refetch.
    nvwa.requests.clear()
    ingest_nvwa(db, nvwa.client())
    assert nvwa.detail_paths_requested() == []
    assert keys(db, "sitemap") == {"/sitemap/1.xml", "/sitemap/2.xml"}


def _future() -> str:
    return datetime(2099, 1, 1, tzinfo=UTC).isoformat()
