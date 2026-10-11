"""NVWA contract (spec §3.4): saved real API responses and detail pages satisfy it."""

import json
from pathlib import Path
from typing import Any

import pytest

from openfoodalerts.contracts import ContractViolation
from openfoodalerts.sources.nvwa.contract import check_detail, check_list

FIXTURES = Path(__file__).parents[1] / "fixtures" / "nvwa"
PAGES = sorted((FIXTURES / "detail").glob("*.html"))


def page(name: str = "ah-pokebowl-allergenen") -> str:
    return (FIXTURES / "detail" / f"{name}.html").read_text(encoding="utf-8")


def list_page(name: str = "list_news_p1") -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", PAGES, ids=lambda p: p.stem)
def test_real_detail_pages_satisfy_the_contract(path: Path) -> None:
    check_detail(path.read_bytes())


@pytest.mark.parametrize("name", ["list_news_p1", "list_archive_p6"])
def test_real_list_responses_satisfy_the_contract(name: str) -> None:
    check_list(list_page(name))


def test_results_without_raw_values_break_the_list_contract() -> None:
    payload = list_page()
    payload["results"][0]["url"] = "/actueel/nieuws/2026/10/24/x"
    with pytest.raises(ContractViolation, match=r"list: results\.0\.url"):
        check_list(payload)


def test_a_list_without_results_breaks_the_list_contract() -> None:
    payload = list_page()
    payload["results"] = []
    with pytest.raises(ContractViolation, match=r"list: results"):
        check_list(payload)


def test_a_page_without_elastic_content_breaks_the_detail_contract() -> None:
    html = page().replace('id="elastic-content"', 'id="content-data"')
    with pytest.raises(ContractViolation, match=r"detail: elastic: "):
        check_detail(html.encode())


def test_a_page_without_dcterms_issued_breaks_the_detail_contract() -> None:
    html = page().replace('name="DCTERMS.issued"', 'name="dcterms.date"')
    with pytest.raises(ContractViolation, match=r"detail: issued"):
        check_detail(html.encode())


def test_a_page_without_rich_text_blocks_breaks_the_detail_contract() -> None:
    html = page().replace("rich-text", "richtext")
    with pytest.raises(ContractViolation, match=r"detail: rich_text_blocks"):
        check_detail(html.encode())


def test_a_page_without_an_intro_breaks_the_detail_contract() -> None:
    html = page().replace('class="intro"', 'class="lead"')
    with pytest.raises(ContractViolation, match=r"detail: intro"):
        check_detail(html.encode())


def test_a_page_that_is_not_utf8_breaks_the_detail_contract() -> None:
    with pytest.raises(ContractViolation, match=r"detail: not UTF-8"):
        check_detail("<html>café</html>".encode("latin-1"))
