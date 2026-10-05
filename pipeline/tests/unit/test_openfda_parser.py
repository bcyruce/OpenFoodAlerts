import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from openfoodalerts.sources.openfda.parser import parse_record


def record(fixtures_dir: Path, name: str, recall_number: str) -> dict[str, Any]:
    body = json.loads((fixtures_dir / "openfda" / name).read_text(encoding="utf-8"))
    return next(r for r in body["results"] if r["recall_number"] == recall_number)


def test_official_fields(fixtures_dir: Path) -> None:
    n = parse_record(record(fixtures_dir, "page_recent.json", "H-0015-2027"))
    assert n.source_key == "H-0015-2027"
    assert n.source_ref == "99933"
    assert n.risk_official == "Class II"
    assert n.status_official == "Ongoing"
    assert n.hazard_text == "Undeclared milk, cheese declared"
    assert n.product_text is not None and n.product_text.startswith("QUESO PALMITA.")
    assert n.notification_type == "enforcement report"
    assert n.source_fields["recalling_firm"] == "QUESO PALMITA GP LLC"
    assert n.source_fields["distribution_pattern"] == "Texas"
    assert n.source_fields["country"] == "United States"
    assert n.source_url.endswith("?search=recall_number:%22H-0015-2027%22")


def test_report_date_becomes_us_eastern_midnight(fixtures_dir: Path) -> None:
    n = parse_record(record(fixtures_dir, "page_recent.json", "H-0015-2027"))
    # 2026-10-14 00:00 America/New_York (EDT, UTC-4)
    assert n.published_at == datetime(2026, 10, 14, 4, 0, tzinfo=UTC)
    assert n.source_fields["recall_initiation_date"] == "2026-09-15"


def test_termination_date_is_kept_as_iso_date(fixtures_dir: Path) -> None:
    n = parse_record(record(fixtures_dir, "terminated.json", "H-1328-2026"))
    assert n.status_official == "Terminated"
    assert n.source_fields["termination_date"] == "2026-09-15"


def test_title_is_short_product_description(fixtures_dir: Path) -> None:
    n = parse_record(record(fixtures_dir, "page_recent.json", "H-0003-2027"))
    assert n.title == "LEASA Alfalfa Sprouts"


@pytest.mark.parametrize(
    ("name", "recall_number"),
    [("supplement.json", "H-1263-2026"), ("class1.json", "H-0016-2027")],
)
def test_supplements_are_food(fixtures_dir: Path, name: str, recall_number: str) -> None:
    n = parse_record(record(fixtures_dir, name, recall_number))
    assert (n.product_type, n.product_type_provenance) == ("food", "rule")


def test_pet_food_is_feed(fixtures_dir: Path) -> None:
    n = parse_record(record(fixtures_dir, "pet.json", "F-1753-2019"))
    assert (n.product_type, n.product_type_provenance) == ("feed", "rule")


def test_cosmetics_are_non_food(fixtures_dir: Path) -> None:
    r = record(fixtures_dir, "page_recent.json", "H-0015-2027")
    r["product_description"] = "Herbal shampoo, 250 mL bottle"
    n = parse_record(r)
    assert (n.product_type, n.product_type_provenance) == ("non-food", "rule")


def test_conflicting_keywords_wait_for_t5(fixtures_dir: Path) -> None:
    r = record(fixtures_dir, "page_recent.json", "H-0015-2027")
    r["product_description"] = "Coconut oil lotion and dog treats gift set"
    n = parse_record(r)
    assert (n.product_type, n.product_type_provenance) == (None, "pending")


@pytest.mark.parametrize(
    "description",
    [
        "Italian bread. Ingredients: wheat flour, water, dough conditioner (whey), salt",
        "Soap Korner Herbalist Red MD Kratom powder",
    ],
)
def test_food_ingredients_that_look_like_cosmetics_stay_food(
    fixtures_dir: Path, description: str
) -> None:
    r = record(fixtures_dir, "page_recent.json", "H-0015-2027")
    r["product_description"] = description
    assert parse_record(r).product_type == "food"
