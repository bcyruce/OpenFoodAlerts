"""`probe-contracts` (spec §3.4, §13) against fake Sources serving the saved responses."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from openfoodalerts.contracts import ContractViolation, SourceUnreachable
from openfoodalerts.db.connection import Connection
from openfoodalerts.http import PoliteClient
from openfoodalerts.probe import default_probes, probe_contracts
from openfoodalerts.sources.nvwa.contract import PROBE_PATH
from openfoodalerts.sources.rasff.client import RasffClient
from openfoodalerts.sources.rasff.contract import PROBE_NOTIF_ID

FIXTURES = Path(__file__).parents[1] / "fixtures"


def fixture(path: str) -> bytes:
    return (FIXTURES / path).read_bytes()


class FakeSources:
    """RASFF, NVWA and openFDA answering the probe requests from the fixtures."""

    def __init__(self) -> None:
        self.overrides: dict[str, Callable[[httpx.Request], httpx.Response]] = {}
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        self.requests.append(f"{request.method} {host}{path}")
        if host in self.overrides:
            return self.overrides[host](request)
        if host == "webgate.ec.europa.eu" and request.method == "POST":
            return httpx.Response(200, content=fixture("rasff/list_page1.json"))
        if host == "webgate.ec.europa.eu" and f"/id/{PROBE_NOTIF_ID}/" in path:
            return httpx.Response(200, content=fixture(f"rasff/details/{PROBE_NOTIF_ID}.json"))
        if host == "www.nvwa.nl" and path == "/api/search":
            return httpx.Response(200, content=fixture("nvwa/list_news_p1.json"))
        if host == "www.nvwa.nl" and path == PROBE_PATH:
            return httpx.Response(
                200,
                content=fixture("nvwa/detail/archive-jumbo-pennywafels-2023.html"),
                headers={"content-type": "text/html; charset=utf-8"},
            )
        if host == "api.fda.gov":
            return httpx.Response(200, content=fixture("openfda/class1.json"))
        return httpx.Response(404)

    def probes(self) -> dict[str, Callable[[], None]]:
        transport = httpx.MockTransport(self.handler)

        def client() -> PoliteClient:
            return PoliteClient(transport=transport, sleep=lambda s: None)

        self.clients = (RasffClient(client()), client(), client())
        return default_probes(*self.clients)


def contract(db: Connection, code: str) -> dict[str, Any]:
    row = db.execute(
        "SELECT contract_status, contract_checked_at, contract_error, last_success_at,"
        " last_error FROM sources WHERE code = %s",
        (code,),
    ).fetchone()
    assert row is not None
    return row


def log_lines(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    return [json.loads(line) for line in capsys.readouterr().err.splitlines() if line]


def test_matching_sources_are_marked_ok(db: Connection, capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeSources()
    results = probe_contracts(db, fake.probes(), clients=fake.clients)
    [job] = [e for e in log_lines(capsys) if e["event"] == "job_finished"]
    assert job["requests"] == 5
    assert job["contracts"] == {"rasff": "ok", "nvwa": "ok", "openfda": "ok"}
    assert {code: r.status for code, r in results.items()} == {
        "rasff": "ok",
        "nvwa": "ok",
        "openfda": "ok",
    }
    for code in ("rasff", "nvwa", "openfda"):
        row = contract(db, code)
        assert row["contract_status"] == "ok"
        assert row["contract_checked_at"] is not None
        assert row["contract_error"] is None
        # A probe is not an ingest run: freshness stays untouched.
        assert row["last_success_at"] is None
    assert len(fake.requests) == 5


def test_a_changed_structure_fails_only_that_source(
    db: Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeSources()
    renamed = json.loads(fixture("openfda/class1.json"))
    for record in renamed["results"]:
        record["recallNumber"] = record.pop("recall_number")
    fake.overrides["api.fda.gov"] = lambda r: httpx.Response(200, json=renamed)
    results = probe_contracts(db, fake.probes())
    assert results["openfda"].status == "failed"
    assert results["rasff"].status == "ok"
    row = contract(db, "openfda")
    assert row["contract_status"] == "failed"
    assert row["contract_error"].startswith("page: results.0.recall_number: Field required")
    assert row["last_error"] is None
    failures = [e for e in log_lines(capsys) if e["event"] == "contract_check_failed"]
    assert [(e["source"], e["status"]) for e in failures] == [("openfda", "failed")]


def test_an_unexpected_status_is_a_contract_failure(db: Connection) -> None:
    fake = FakeSources()
    fake.overrides["www.nvwa.nl"] = lambda r: httpx.Response(410, text="gone")
    results = probe_contracts(db, fake.probes())
    assert results["nvwa"].status == "failed"
    assert contract(db, "nvwa")["contract_error"] == "list: HTTP 410"


def test_html_instead_of_json_is_a_contract_failure(db: Connection) -> None:
    fake = FakeSources()
    fake.overrides["webgate.ec.europa.eu"] = lambda r: httpx.Response(
        200, text="<html>maintenance</html>", headers={"content-type": "text/html"}
    )
    probe_contracts(db, fake.probes())
    assert contract(db, "rasff")["contract_error"] == "list: not JSON (content-type text/html)"


def test_server_errors_and_network_errors_mean_unreachable(db: Connection) -> None:
    fake = FakeSources()
    fake.overrides["webgate.ec.europa.eu"] = lambda r: httpx.Response(503)

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    fake.overrides["api.fda.gov"] = refuse
    results = probe_contracts(db, fake.probes())
    assert results["rasff"].status == "unreachable"
    assert contract(db, "rasff")["contract_error"] == "list: HTTP 503"
    assert results["openfda"].status == "unreachable"
    assert contract(db, "openfda")["contract_error"] == "ConnectError"
    assert results["nvwa"].status == "ok"


def test_a_passing_probe_clears_an_earlier_failure(db: Connection) -> None:
    def broken() -> None:
        raise ContractViolation("detail: reference: Field required")

    probe_contracts(db, {"rasff": broken})
    assert contract(db, "rasff")["contract_status"] == "failed"
    probe_contracts(db, {"rasff": lambda: None})
    row = contract(db, "rasff")
    assert row["contract_status"] == "ok"
    assert row["contract_error"] is None


def test_an_unexpected_error_in_a_probe_counts_as_failed(db: Connection) -> None:
    def buggy() -> None:
        raise KeyError("notifications")

    def offline() -> None:
        raise SourceUnreachable("detail: HTTP 502")

    results = probe_contracts(db, {"rasff": buggy, "nvwa": offline})
    assert results["rasff"].status == "failed"
    # Only the type is stored (shown on /api/health); the message goes to the job log.
    assert contract(db, "rasff")["contract_error"] == "KeyError (see the job log)"
    assert results["nvwa"].status == "unreachable"
    assert contract(db, "openfda")["contract_status"] is None
