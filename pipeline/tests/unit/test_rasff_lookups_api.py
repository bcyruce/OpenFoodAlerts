"""The lookup API over the committed seed files in db/seed/rasff/ (used by the parser)."""

import datetime as dt
from pathlib import Path

import pytest

from openfoodalerts.sources.rasff.lookups import (
    Dictionary,
    Lookup,
    LookupEntry,
    UnknownLookupValue,
    lookup,
    read_seed,
    write_seed,
)

# Counts measured on 2026-10-24 (spec §3.1) and re-checked on 2026-10-25.
EXPECTED_COUNTS = {
    Dictionary.HAZARD_CATEGORY: 30,
    Dictionary.PRODUCT_CATEGORY: 37,
    Dictionary.NOTIFICATION_CLASSIFICATION: 6,
    Dictionary.RISK_DECISION: 5,
    Dictionary.PRODUCT_TYPE: 5,
}


@pytest.mark.parametrize(("dictionary", "count"), EXPECTED_COUNTS.items())
def test_committed_seed_counts_match_spec(dictionary: Dictionary, count: int) -> None:
    assert len(lookup(dictionary)) == count


def test_every_dictionary_has_a_seed_file() -> None:
    for d in Dictionary:
        assert len(lookup(d)) > 0, d


def test_classification_ids_match_spec() -> None:
    classifications = lookup(Dictionary.NOTIFICATION_CLASSIFICATION)
    assert classifications.id_for("alert notification") == 306
    assert classifications.name_for(302) == "news"


def test_product_type_ids_match_spec() -> None:
    types = lookup(Dictionary.PRODUCT_TYPE)
    assert {e.name: e.id for e in types} == {
        "food": 283,
        "feed": 282,
        "food contact material": 281,
        "animals": 284,
        "other": 286,
    }


def test_name_lookup_ignores_case_and_extra_whitespace() -> None:
    hazards = lookup(Dictionary.HAZARD_CATEGORY)
    assert hazards.id_for("Pathogenic  micro-organisms ") == hazards.id_for(
        "pathogenic micro-organisms"
    )


def test_unknown_values_raise_or_return_none() -> None:
    hazards = lookup(Dictionary.HAZARD_CATEGORY)
    with pytest.raises(UnknownLookupValue):
        hazards.id_for("biocontaminants")
    with pytest.raises(UnknownLookupValue):
        hazards.name_for(-1)
    assert hazards.get_by_name("biocontaminants") is None
    assert hazards.get_by_id(-1) is None


def test_countries_resolve_by_iso_code() -> None:
    countries = lookup(Dictionary.COUNTRY)
    nl = countries.get_by_code("nl")
    assert nl is not None
    assert nl.name == "Netherlands"
    assert countries.name_for(nl.id) == "Netherlands"
    assert countries.get_by_code("ZZ") is None


def test_duplicate_names_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        Lookup(Dictionary.RISK_DECISION, (LookupEntry(1, "serious"), LookupEntry(2, "Serious")))


def test_seed_file_round_trips_and_is_sorted(tmp_path: Path) -> None:
    entries = [LookupEntry(20, "Türkiye", "TR"), LookupEntry(10, "Austria", "AT")]
    path = write_seed(Dictionary.COUNTRY, entries, dt.date(2026, 10, 25), tmp_path)
    text = path.read_text(encoding="utf-8")
    assert text.index("Austria") < text.index("Türkiye")
    assert read_seed(Dictionary.COUNTRY, tmp_path) == sorted(entries)
