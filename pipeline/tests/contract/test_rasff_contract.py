"""RASFF contract (spec §3.4): every saved real response satisfies it; broken ones do not."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from openfoodalerts.contracts import ContractViolation
from openfoodalerts.sources.rasff.contract import check_detail, check_list

FIXTURES = Path(__file__).parents[1] / "fixtures" / "rasff"
DETAILS = sorted((FIXTURES / "details").glob("*.json"))


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", DETAILS, ids=lambda p: p.stem)
def test_real_details_satisfy_the_contract(path: Path) -> None:
    check_detail(load(path))


def test_real_list_page_satisfies_the_contract() -> None:
    check_list(load(FIXTURES / "list_page1.json"))


def _detail() -> dict[str, Any]:
    body: dict[str, Any] = copy.deepcopy(load(FIXTURES / "details" / "881995.json"))
    return body


def test_a_renamed_reference_breaks_the_detail_contract() -> None:
    body = _detail()
    body["notificationReference"] = body.pop("reference")
    with pytest.raises(ContractViolation, match=r"detail: reference: Field required"):
        check_detail(body)


def test_a_new_date_format_breaks_the_detail_contract() -> None:
    body = _detail()
    body["ecValidationDate"] = "2026-10-23T16:50:28Z"
    with pytest.raises(ContractViolation, match=r"ecValidationDate"):
        check_detail(body)


def test_hazards_turned_into_an_object_break_the_detail_contract() -> None:
    body = _detail()
    body["product"]["hazards"] = {"items": body["product"]["hazards"]}
    with pytest.raises(ContractViolation, match=r"product\.hazards"):
        check_detail(body)


def test_hazard_category_without_description_breaks_the_detail_contract() -> None:
    body = _detail()
    body["product"]["hazards"][0]["hazardCategory"] = {"id": 1, "name": "pesticide residues"}
    with pytest.raises(ContractViolation, match=r"product\.hazards\.0\.hazardCategory"):
        check_detail(body)


def test_a_list_without_notifications_breaks_the_list_contract() -> None:
    payload = load(FIXTURES / "list_page1.json")
    payload["content"] = payload.pop("notifications")
    with pytest.raises(ContractViolation, match=r"list: notifications: Field required"):
        check_list(payload)


def test_an_empty_first_page_breaks_the_list_contract() -> None:
    payload = load(FIXTURES / "list_page1.json")
    payload["notifications"] = []
    with pytest.raises(ContractViolation, match=r"list: notifications"):
        check_list(payload)


def test_a_violation_lists_field_paths_but_not_values() -> None:
    body = _detail()
    body["reference"] = "officer@authority.example"
    with pytest.raises(ContractViolation) as caught:
        check_detail(body)
    assert "reference" in str(caught.value)
    assert "@" not in str(caught.value)
