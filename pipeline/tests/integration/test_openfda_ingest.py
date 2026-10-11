import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from openfoodalerts.db.connection import Connection
from openfoodalerts.http import PoliteClient
from openfoodalerts.sources.openfda.ingest import ingest_openfda

NEXT = "https://api.fda.gov/food/enforcement.json?limit=1000&search_after=abc"


class FakeOpenFDA:
    """Serves fixture pages the way openFDA does: meta probe, then search_after pages."""

    def __init__(self, fixtures: Path, last_updated: str = "2026-10-14") -> None:
        self.pages = [
            json.loads((fixtures / "openfda" / n).read_text(encoding="utf-8"))
            for n in ("page_recent.json", "supplement.json")
        ]
        self.last_updated = last_updated
        self.requests: list[httpx.URL] = []
        self.not_found = False

    def meta(self) -> dict[str, Any]:
        return {"last_updated": self.last_updated, "results": {"skip": 0, "limit": 1, "total": 8}}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request.url)
        params = request.url.params
        if self.not_found:
            return httpx.Response(404, json={"error": {"code": "NOT_FOUND"}})
        if params.get("limit") == "1":
            return httpx.Response(200, json={"meta": self.meta(), "results": []})
        assert "skip" not in params
        if "search_after" in params:
            page = {"meta": self.meta(), "results": self.pages[1]["results"]}
            return httpx.Response(200, json=page)
        assert params["sort"] == "report_date:desc"
        return httpx.Response(
            200,
            json={"meta": self.meta(), "results": self.pages[0]["results"]},
            headers={"Link": f'<{NEXT}>; rel="next"'},
        )

    def client(self) -> PoliteClient:
        return PoliteClient(transport=httpx.MockTransport(self.handler), sleep=lambda s: None)


def archived_keys(db: Connection) -> list[str]:
    rows = db.execute(
        "SELECT DISTINCT source_key FROM raw_records WHERE kind = 'detail' ORDER BY 1"
    ).fetchall()
    return [r["source_key"] for r in rows]


def test_full_sync_archives_every_record_across_pages(db: Connection, fixtures_dir: Path) -> None:
    fda = FakeOpenFDA(fixtures_dir)
    stats = ingest_openfda(db, fda.client())
    assert stats.new == 8
    assert len(archived_keys(db)) == 8
    assert any("search_after" in str(u) for u in fda.requests)


def test_unchanged_last_updated_skips_sync(db: Connection, fixtures_dir: Path) -> None:
    fda = FakeOpenFDA(fixtures_dir)
    ingest_openfda(db, fda.client())
    fda.requests.clear()
    stats = ingest_openfda(db, fda.client())
    assert len(fda.requests) == 1
    assert stats.new == stats.changed == 0


def test_new_snapshot_detects_changed_records(db: Connection, fixtures_dir: Path) -> None:
    fda = FakeOpenFDA(fixtures_dir)
    ingest_openfda(db, fda.client())
    fda.last_updated = "2026-10-21"
    fda.pages[0]["results"][0]["status"] = "Terminated"
    stats = ingest_openfda(db, fda.client())
    assert (stats.new, stats.changed, stats.unchanged) == (0, 1, 7)


def test_404_is_an_empty_result(db: Connection, fixtures_dir: Path) -> None:
    fda = FakeOpenFDA(fixtures_dir)
    fda.not_found = True
    stats = ingest_openfda(db, fda.client())
    assert stats.new == 0
    assert archived_keys(db) == []


def test_api_key_is_sent_when_configured(
    db: Connection, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENFDA_API_KEY", "k123")
    fda = FakeOpenFDA(fixtures_dir)
    ingest_openfda(db, fda.client())
    assert all(u.params.get("api_key") == "k123" for u in fda.requests)


def test_api_key_is_never_archived(
    db: Connection, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENFDA_API_KEY", "k123")
    ingest_openfda(db, FakeOpenFDA(fixtures_dir).client())
    rows = db.execute("SELECT url FROM raw_records").fetchall()
    assert rows
    assert not [r["url"] for r in rows if "k123" in r["url"]]
