"""openFDA contract (spec §3.3, §3.4): saved real responses satisfy it."""

import json
from pathlib import Path
from typing import Any

import pytest

from openfoodalerts.contracts import ContractViolation
from openfoodalerts.sources.openfda.contract import check_page

FIXTURES = Path(__file__).parents[1] / "fixtures" / "openfda"
PAGES = [p for p in sorted(FIXTURES.glob("*.json")) if p.stem != "not_found"]


def load(name: str = "page_recent") -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", PAGES, ids=lambda p: p.stem)
def test_real_responses_satisfy_the_contract(path: Path) -> None:
    check_page(json.loads(path.read_text(encoding="utf-8")))


def test_a_404_body_breaks_the_contract() -> None:
    with pytest.raises(ContractViolation, match=r"page: meta: Field required"):
        check_page(load("not_found"))


def test_a_new_date_format_breaks_the_contract() -> None:
    payload = load()
    payload["results"][0]["report_date"] = "2026-10-14"
    with pytest.raises(ContractViolation, match=r"page: results\.0\.report_date"):
        check_page(payload)


def test_a_missing_recall_number_breaks_the_contract() -> None:
    payload = load()
    del payload["results"][0]["recall_number"]
    with pytest.raises(ContractViolation, match=r"page: results\.0\.recall_number"):
        check_page(payload)


def test_a_missing_last_updated_breaks_the_contract() -> None:
    payload = load()
    del payload["meta"]["last_updated"]
    with pytest.raises(ContractViolation, match=r"page: meta\.last_updated"):
        check_page(payload)
