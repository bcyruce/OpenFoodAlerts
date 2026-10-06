"""`backfill-rasff` against a fake RASFF Window serving the real detail fixtures."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from openfoodalerts.cli import app
from openfoodalerts.db.connection import Connection
from openfoodalerts.parse.run import parse
from openfoodalerts.sources.rasff.backfill import backfill_rasff
from openfoodalerts.sources.rasff.client import RasffClient

DETAILS = Path(__file__).parents[1] / "fixtures" / "rasff" / "details"
CONTACT = [{"contactPerson": {"email": "officer@authority.example"}}]


class FakeRasff:
    """List pages in the order given, details by notifId; detail bodies carry contacts."""

    def __init__(self) -> None:
        bodies = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(DETAILS.glob("*.json"))]
        self.details: dict[int, dict[str, Any]] = {
            b["id"]: b | {"additionalInformations": CONTACT} for b in bodies
        }
        self.detail_requests: list[int] = []
        self.list_requests: list[dict[str, Any]] = []
        self.missing: set[int] = set()
        self.interrupt_after: int | None = None

    def _list(self, body: dict[str, Any]) -> httpx.Response:
        self.list_requests.append(body)
        page, size = body["parameters"]["pageNumber"], body["parameters"]["itemsPerPage"]
        items = [{"notifId": i, "reference": d["reference"]} for i, d in self.details.items()]
        chunk = items[(page - 1) * size : page * size]
        pages = -(-len(items) // size)
        return httpx.Response(
            200,
            json={"notifications": chunk, "totalPages": pages, "totalElements": len(items)},
            headers={"X-Rate-Limit-Remaining": "49"},
        )

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return self._list(json.loads(request.content))
        notif_id = int(request.url.path.rstrip("/").split("/")[-2])
        if self.interrupt_after is not None and len(self.detail_requests) >= self.interrupt_after:
            raise KeyboardInterrupt
        self.detail_requests.append(notif_id)
        if notif_id in self.missing:
            return httpx.Response(404, json={"status": "NOT_FOUND"})
        return httpx.Response(
            200, json=self.details[notif_id], headers={"X-Rate-Limit-Remaining": "49"}
        )

    def client(self) -> RasffClient:
        return RasffClient.create(transport=httpx.MockTransport(self.handler), sleep=lambda s: None)


def raw_keys(db: Connection, kind: str) -> list[str]:
    rows = db.execute(
        "SELECT source_key FROM raw_records WHERE kind = %s ORDER BY id", (kind,)
    ).fetchall()
    return [r["source_key"] for r in rows]


def test_backfill_archives_every_list_page_and_detail(db: Connection) -> None:
    fake = FakeRasff()
    stats = backfill_rasff(db, fake.client(), items_per_page=5)
    assert len(fake.list_requests) == 4
    assert len(raw_keys(db, "list")) == 4
    assert sorted(raw_keys(db, "detail")) == sorted(d["reference"] for d in fake.details.values())
    assert stats.new == 16
    assert stats.extra["pages"] == 4
    # the list page key is the canonical request body
    assert raw_keys(db, "list")[0] == (
        'consolidated:{"parameters":{"itemsPerPage":5,"pageNumber":1}}'
    )


def test_rerun_skips_notifications_with_an_archived_detail(db: Connection) -> None:
    fake = FakeRasff()
    backfill_rasff(db, fake.client(), items_per_page=5, max_details=6)
    assert len(fake.detail_requests) == 6
    fake.detail_requests.clear()
    stats = backfill_rasff(db, fake.client(), items_per_page=5)
    assert len(fake.detail_requests) == 10
    assert stats.extra["skipped"] == 6
    assert len(raw_keys(db, "detail")) == 16


def test_interrupted_backfill_keeps_its_progress(db: Connection) -> None:
    fake = FakeRasff()
    fake.interrupt_after = 7
    with pytest.raises(KeyboardInterrupt):
        backfill_rasff(db, fake.client(), items_per_page=5)
    assert len(raw_keys(db, "detail")) == 7
    fake.interrupt_after = None
    fake.detail_requests.clear()
    backfill_rasff(db, fake.client(), items_per_page=5)
    assert len(fake.detail_requests) == 9
    assert len(set(raw_keys(db, "detail"))) == len(raw_keys(db, "detail")) == 16


def test_a_missing_detail_is_reported_and_retried_next_run(db: Connection) -> None:
    fake = FakeRasff()
    fake.missing = {881995}
    stats = backfill_rasff(db, fake.client(), items_per_page=50)
    assert stats.extra["missing"] == 1
    assert "2026.9489" not in raw_keys(db, "detail")
    fake.missing.clear()
    fake.detail_requests.clear()
    backfill_rasff(db, fake.client(), items_per_page=50)
    assert fake.detail_requests == [881995]


def test_cli_runs_a_bounded_backfill_and_resumes_after_ctrl_c(
    db: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeRasff()
    clients = iter([fake.client(), fake.client()])
    monkeypatch.setattr(RasffClient, "create", classmethod(lambda cls, **kw: next(clients)))
    runner = CliRunner()
    result = runner.invoke(app, ["backfill-rasff", "--max-pages", "1", "--max-details", "2"])
    assert result.exit_code == 0, result.output
    assert len(raw_keys(db, "detail")) == 2
    fake.interrupt_after = 3
    result = runner.invoke(app, ["backfill-rasff"])
    assert result.exit_code == 130
    assert "re-run" in result.output
    assert len(raw_keys(db, "detail")) == 3


def test_raw_detail_is_kept_whole_but_contacts_never_reach_parsed_tables(db: Connection) -> None:
    fake = FakeRasff()
    backfill_rasff(db, fake.client(), items_per_page=50, max_details=3)
    row = db.execute("SELECT body FROM raw_records WHERE kind = 'detail' LIMIT 1").fetchone()
    assert row is not None
    assert b"officer@authority.example" in bytes(row["body"])
    parse(db, ["rasff"])
    dump = db.execute(
        "SELECT string_agg(to_jsonb(n)::text, '') AS t FROM notifications n"
    ).fetchone()
    assert dump is not None
    assert "officer@authority.example" not in dump["t"]
    assert "contactPerson" not in dump["t"]
