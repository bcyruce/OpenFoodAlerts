"""`ofa seed-rasff-lookups`: fetch live dictionaries, diff against seed files, write nothing.

Fixtures: tests/fixtures/rasff/lookups/seed/ is a small seed directory; live/ holds the
matching live responses with deliberate changes (hazard categories: one renamed, one
removed, one added; countries: one code changed).
"""

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from openfoodalerts.cli import app
from openfoodalerts.http import PoliteClient
from openfoodalerts.sources.rasff import lookups
from openfoodalerts.sources.rasff.lookups import (
    BASE_URL,
    Dictionary,
    RasffLookupFetchError,
    check_against_seed,
    format_report,
)

runner = CliRunner()


@pytest.fixture
def lookup_fixtures(fixtures_dir: Path) -> Path:
    return fixtures_dir / "rasff" / "lookups"


def serve_dir(live_dir: Path, seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = str(request.url).removeprefix(BASE_URL)
        stem = path.split("/")[0]
        file = live_dir / f"{stem}.json"
        if not file.exists():
            return httpx.Response(404)
        return httpx.Response(200, content=file.read_bytes())

    return httpx.MockTransport(handler)


def serve_seed_as_live(seed_dir: Path, seen: list[httpx.Request]) -> httpx.MockTransport:
    """Answer every dictionary request with exactly what the seed file holds."""

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = str(request.url).removeprefix(BASE_URL)
        d = next(d for d in Dictionary if d.endpoint == path)
        if d is Dictionary.COUNTRY:
            items = [
                {"id": e.id, "englishShortName": e.name, "alpha2Code": e.code}
                for e in lookups.read_seed(d, seed_dir)
            ]
        else:
            items = [{"id": e.id, "description": e.name} for e in lookups.read_seed(d, seed_dir)]
        return httpx.Response(200, json={d.response_key: items})

    return httpx.MockTransport(handler)


def client_for(transport: httpx.MockTransport, sleeps: list[float]) -> PoliteClient:
    return PoliteClient(
        min_interval=lookups.REQUEST_INTERVAL,
        transport=transport,
        sleep=sleeps.append,
        clock=lambda: 0.0,
    )


def snapshot(directory: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(directory.iterdir())}


def test_identical_dictionaries_report_no_changes(lookup_fixtures: Path) -> None:
    seed_dir = lookup_fixtures / "seed"
    seen: list[httpx.Request] = []
    sleeps: list[float] = []
    with client_for(serve_seed_as_live(seed_dir, seen), sleeps) as client:
        diffs = check_against_seed(client, seed_dir)
    assert not any(d.has_changes for d in diffs)
    assert "All RASFF dictionaries match" in format_report(diffs)


def test_fetches_each_dictionary_once_politely(lookup_fixtures: Path) -> None:
    seen: list[httpx.Request] = []
    sleeps: list[float] = []
    with client_for(serve_dir(lookup_fixtures / "live", seen), sleeps) as client:
        check_against_seed(client, lookup_fixtures / "seed")
    assert {r.method for r in seen} == {"GET"}
    assert sorted(str(r.url) for r in seen) == sorted(BASE_URL + d.endpoint for d in Dictionary)
    assert sleeps == [lookups.REQUEST_INTERVAL] * (len(Dictionary) - 1)


def test_diff_report_lists_added_removed_and_renamed(lookup_fixtures: Path) -> None:
    seen: list[httpx.Request] = []
    with client_for(serve_dir(lookup_fixtures / "live", seen), []) as client:
        diffs = check_against_seed(client, lookup_fixtures / "seed")
    report = format_report(diffs)
    assert "hazard_categories: CHANGED (seed 5, live 5)" in report
    assert "+ added    26845 'environmental pollutants'" in report
    assert "- removed  99999 'gone'" in report
    assert "~ renamed  21782 'biocontaminants' -> 21782 'biological contaminants'" in report
    assert "~ renamed  5014 'United Kingdom' [GB] -> 5014 'United Kingdom' [UK]" in report
    assert "product_categories: identical (4 entries)" in report
    assert "2 dictionary(ies) differ" in report


def test_unexpected_response_shape_is_an_error(tmp_path: Path, lookup_fixtures: Path) -> None:
    live = tmp_path / "live"
    live.mkdir()
    for f in (lookup_fixtures / "live").iterdir():
        (live / f.name).write_bytes(f.read_bytes())
    (live / "riskDecision.json").write_text(json.dumps({"somethingElse": []}))
    with (
        client_for(serve_dir(live, []), []) as client,
        pytest.raises(RasffLookupFetchError, match="riskDecisions"),
    ):
        check_against_seed(client, lookup_fixtures / "seed")


def test_http_error_is_an_error(tmp_path: Path, lookup_fixtures: Path) -> None:
    with (
        client_for(serve_dir(tmp_path, []), []) as client,
        pytest.raises(RasffLookupFetchError, match="HTTP 404"),
    ):
        check_against_seed(client, lookup_fixtures / "seed")


def test_non_json_response_is_an_error(lookup_fixtures: Path) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"<html>"))
    with (
        client_for(transport, []) as client,
        pytest.raises(RasffLookupFetchError, match="not JSON"),
    ):
        check_against_seed(client, lookup_fixtures / "seed")


def test_malformed_entry_is_an_error() -> None:
    with pytest.raises(RasffLookupFetchError, match="unexpected entry"):
        lookups.parse_response(Dictionary.RISK_DECISION, {"riskDecisions": [{"id": "x"}]})


@pytest.fixture
def use_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[httpx.MockTransport, Path], None]:
    def apply(transport: httpx.MockTransport, seed_dir: Path) -> None:
        monkeypatch.setenv(lookups.SEED_DIR_ENV, str(seed_dir))
        monkeypatch.setattr(lookups, "make_client", lambda: client_for(transport, []))

    return apply


def test_cli_exits_0_when_identical(
    lookup_fixtures: Path, use_transport: Callable[[httpx.MockTransport, Path], None]
) -> None:
    seed_dir = lookup_fixtures / "seed"
    use_transport(serve_seed_as_live(seed_dir, []), seed_dir)
    result = runner.invoke(app, ["seed-rasff-lookups"])
    assert result.exit_code == 0, result.output
    assert "All RASFF dictionaries match" in result.output


def test_cli_exits_3_on_differences_and_writes_nothing(
    lookup_fixtures: Path, use_transport: Callable[[httpx.MockTransport, Path], None]
) -> None:
    seed_dir = lookup_fixtures / "seed"
    before = snapshot(seed_dir)
    use_transport(serve_dir(lookup_fixtures / "live", []), seed_dir)
    result = runner.invoke(app, ["seed-rasff-lookups"])
    assert result.exit_code == 3, result.output
    assert "hazard_categories: CHANGED" in result.output
    assert snapshot(seed_dir) == before


def test_cli_exits_1_on_fetch_error(
    tmp_path: Path,
    lookup_fixtures: Path,
    use_transport: Callable[[httpx.MockTransport, Path], None],
) -> None:
    use_transport(serve_dir(tmp_path, []), lookup_fixtures / "seed")
    result = runner.invoke(app, ["seed-rasff-lookups"])
    assert result.exit_code == 1
    assert "HTTP 404" in result.output


def test_export_writes_seed_files_from_live(
    tmp_path: Path,
    lookup_fixtures: Path,
    use_transport: Callable[[httpx.MockTransport, Path], None],
) -> None:
    use_transport(serve_dir(lookup_fixtures / "live", []), tmp_path)
    result = runner.invoke(app, ["export-rasff-lookups"])
    assert result.exit_code == 0, result.output
    hazards = lookups.read_seed(Dictionary.HAZARD_CATEGORY, tmp_path)
    assert hazards[0] == lookups.LookupEntry(21782, "biological contaminants")
    assert len(hazards) == 5
