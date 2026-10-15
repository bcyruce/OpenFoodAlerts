"""Logic behind eval/label_app.py: what to show next, validation, append and resume."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from openfoodalerts.eval.files import ItemRow, read_labels
from openfoodalerts.eval.job import non_food_items
from openfoodalerts.eval.labeling import LabelSession, Options, default_options, validate

NOW = datetime(2026, 10, 26, 8, 30, tzinfo=UTC)


def row(item_id: str, agreement: bool = False, source: str = "nvwa") -> ItemRow:
    return ItemRow(
        item_id=item_id,
        split="dev",
        source=source,
        source_key=f"/{item_id}",
        source_url="https://www.nvwa.nl/x",
        published_on="2026-10-01",
        stratum="nvwa:allergens",
        noise_audit=False,
        agreement=agreement,
        official_categories=(),
        input={
            "title": "Veiligheidswaarschuwing Gazpacho van Marqt (melkallergie)",
            "summary": "Op het etiket ontbreekt het allergeen melk. Product uit Spanje.",
            "products": "",
        },
    )


ITEMS = [row("nv-1", agreement=True), row("nv-2"), row("nv-3", agreement=True)]
GOOD = {
    "hazard_category": "allergens",
    "product_category": "soups, broths, sauces and condiments",
    "hazard": "allergeen melk",
    "origin_country": "ES",
    "product_type": "food",
}


@pytest.fixture
def options() -> Options:
    return default_options(("allergens", "foreign bodies", "other"))


def session(tmp_path: Path, annotator: str = "A") -> LabelSession:
    return LabelSession(ITEMS, tmp_path / "labels.csv", annotator, "v1")


def test_a_starts_at_the_first_item_and_moves_on_after_saving(tmp_path: Path) -> None:
    s = session(tmp_path)
    assert s.next_item() == ITEMS[0]
    assert s.progress() == (0, 3)
    s.save(ITEMS[0], GOOD, note="", now=NOW)
    assert s.next_item() == ITEMS[1]
    assert s.progress() == (1, 3)


def test_labelling_resumes_from_the_csv(tmp_path: Path) -> None:
    session(tmp_path).save(ITEMS[0], GOOD, note="", now=NOW)
    session(tmp_path).save(ITEMS[1], GOOD, note="", now=NOW)
    assert session(tmp_path).next_item() == ITEMS[2]


def test_the_appended_row_has_annotator_guideline_and_time(tmp_path: Path) -> None:
    session(tmp_path).save(ITEMS[0], GOOD, note="melk staat in titel", now=NOW)
    [saved] = read_labels(tmp_path / "labels.csv")
    assert saved == {
        "item_id": "nv-1",
        "annotator": "A",
        "guideline_version": "v1",
        **GOOD,
        "note": "melk staat in titel",
        "labelled_at": "2026-10-26T08:30:00+00:00",
    }


def test_b_only_gets_the_agreement_subset_and_never_sees_a(tmp_path: Path) -> None:
    session(tmp_path, "A").save(ITEMS[0], GOOD, note="", now=NOW)
    b = session(tmp_path, "B")
    assert b.next_item() == ITEMS[0]  # A's work does not count for B
    assert b.progress() == (0, 2)
    assert b.own_label("nv-1") is None
    b.save(ITEMS[0], GOOD | {"hazard_category": "other"}, note="", now=NOW)
    assert b.next_item() == ITEMS[2]
    assert b.own_label("nv-1") == GOOD | {"hazard_category": "other"}


def test_a_new_guideline_version_starts_over(tmp_path: Path) -> None:
    session(tmp_path).save(ITEMS[0], GOOD, note="", now=NOW)
    v2 = LabelSession(ITEMS, tmp_path / "labels.csv", "A", "v2")
    assert v2.next_item() == ITEMS[0]


def test_valid_labels_pass(options: Options) -> None:
    assert validate(ITEMS[0], GOOD, options) == []
    no_span = GOOD | {"hazard": "none", "origin_country": "unknown", "hazard_category": "unsure"}
    assert validate(ITEMS[0], no_span, options) == []


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"hazard_category": "salmonella"}, "hazard_category"),
        ({"hazard_category": ""}, "hazard_category"),
        ({"product_category": "toys"}, "product_category"),
        ({"hazard": "allergeen ei"}, "verbatim"),
        ({"hazard": ""}, "hazard"),
        ({"hazard": "allergeen melk. Product"}, None),  # within one field: fine
        ({"hazard": "(melkallergie)\nOp het"}, "verbatim"),  # across fields: not
        ({"origin_country": "Spain"}, "origin_country"),
        ({"origin_country": "es"}, None),  # normalised to ES
        ({"product_type": "toy"}, "product_type"),
    ],
)
def test_invalid_labels_are_reported(
    options: Options, change: dict[str, str], message: str | None
) -> None:
    errors = validate(ITEMS[0], GOOD | change, options)
    if message is None:
        assert errors == []
    else:
        assert len(errors) == 1 and message in errors[0]


def test_options_come_from_the_taxonomy_and_rasff_seeds(options: Options) -> None:
    assert options.hazard_categories == ("allergens", "foreign bodies", "other", "unsure")
    assert "fruits and vegetables" in options.product_categories
    assert options.product_categories[-1] == "unsure"
    assert "NL" in options.countries and options.countries[0] == "unknown"
    assert "ECDC" not in options.countries
    assert options.product_types == ("food", "feed", "food contact material", "non-food")


def test_items_labelled_non_food_are_found_for_exclusion(tmp_path: Path) -> None:
    a = session(tmp_path)
    a.save(ITEMS[0], GOOD | {"product_type": "non-food"}, note="", now=NOW)
    a.save(ITEMS[1], GOOD, note="", now=NOW)
    a.save(ITEMS[1], GOOD | {"product_type": "non-food"}, note="corrected", now=NOW)
    a.save(ITEMS[0], GOOD, note="corrected back", now=NOW)
    assert non_food_items(tmp_path) == ["nv-2"]
