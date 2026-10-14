"""RASFF silver set: single-category Notifications, stratified, with the excluded share."""

from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from openfoodalerts.eval.labelset import Taxonomy, load_taxonomy
from openfoodalerts.eval.silver import RasffRecord, build_silver, write_silver

TAXONOMY = (
    "rasff_id,name_en,notifications_since_2020-01-01,label\n"
    "21801,pathogenic micro-organisms,6000,pathogenic micro-organisms\n"
    "21798,allergens,500,allergens\n"
    "26580,novel food,352,GMO / novel food\n"
    "26581,genetically modified,103,GMO / novel food\n"
)


@pytest.fixture
def taxonomy(tmp_path: Path) -> Taxonomy:
    path = tmp_path / "v1-draft.csv"
    path.write_text(TAXONOMY, encoding="utf-8")
    return load_taxonomy(path)


def rec(key: str, *categories: int) -> RasffRecord:
    return RasffRecord(key, date(2024, 5, 1), f"subject {key}", categories)


def records() -> list[RasffRecord]:
    out = [rec(f"P{i}", 21801) for i in range(600)]
    out += [rec(f"A{i}", 21798, 21798) for i in range(50)]
    out += [rec(f"G{i}", 26580, 26581) for i in range(10)]  # one label after merging
    out += [rec(f"M{i}", 21801, 21798) for i in range(40)]  # two labels
    out += [rec(f"N{i}") for i in range(100)]  # no Hazard
    return out


def test_only_single_label_notifications_and_the_excluded_share(taxonomy: Taxonomy) -> None:
    silver = build_silver(records(), taxonomy, size=2000, seed=1)
    assert len(silver.rows) == 660
    assert not any(r.source_key.startswith(("M", "N")) for r in silver.rows)
    assert silver.stats.with_hazards == 700
    assert silver.stats.no_hazards == 100
    assert silver.stats.multi_label == 40
    assert silver.stats.multi_category == 50  # G: novel food + genetically modified
    assert silver.stats.excluded_share == pytest.approx(40 / 700)


def test_stratified_with_a_floor_for_small_labels(taxonomy: Taxonomy) -> None:
    silver = build_silver(records(), taxonomy, size=100, seed=1)
    counts = Counter(r.label for r in silver.rows)
    assert sum(counts.values()) == 100
    assert counts["GMO / novel food"] == 10  # floor min(available, 25)
    assert counts["allergens"] == 25
    assert counts["pathogenic micro-organisms"] == 65


def test_eval_items_are_kept_out_and_output_is_reproducible(
    taxonomy: Taxonomy, tmp_path: Path
) -> None:
    first = build_silver(records(), taxonomy, size=100, seed=1, exclude={"A1", "A2"})
    assert not {"A1", "A2"} & {r.source_key for r in first.rows}
    again = build_silver(
        list(reversed(records())), taxonomy, size=100, seed=1, exclude={"A1", "A2"}
    )
    assert first.rows == again.rows
    path = tmp_path / "silver.csv"
    write_silver(path, first.rows)
    header, line = path.read_text(encoding="utf-8").splitlines()[:2]
    assert header == "source_key,published_on,label,rasff_categories,subject"
    assert line.count(",") >= 4
