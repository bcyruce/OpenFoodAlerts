from pathlib import Path

import pytest

from openfoodalerts.eval.labelset import default_taxonomy_path, load_taxonomy

DRAFT = (
    "rasff_id,name_en,notifications_since_2020-01-01,label\n"
    "21801,pathogenic micro-organisms,6825,pathogenic micro-organisms\n"
    "21798,allergens,535,allergens\n"
    "26580,novel food,352,GMO / novel food\n"
    "26581,genetically modified,103,GMO / novel food\n"
    "21788,packaging defective / incorrect,6,other\n"
)


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_labels_are_distinct_in_file_order_with_other_last(tmp_path: Path) -> None:
    taxonomy = load_taxonomy(write(tmp_path, "v1-draft.csv", DRAFT))
    assert taxonomy.labels == (
        "pathogenic micro-organisms",
        "allergens",
        "GMO / novel food",
        "other",
    )


def test_category_names_and_ids_map_to_merged_labels(tmp_path: Path) -> None:
    taxonomy = load_taxonomy(write(tmp_path, "v1-draft.csv", DRAFT))
    assert taxonomy.label_for_name("Genetically Modified") == "GMO / novel food"
    assert taxonomy.label_for_name("packaging defective / incorrect") == "other"
    assert taxonomy.label_for_rasff_id(21798) == "allergens"
    assert taxonomy.label_for_rasff_id(1) is None


def test_counts_and_category_ids_per_label(tmp_path: Path) -> None:
    taxonomy = load_taxonomy(write(tmp_path, "v1-draft.csv", DRAFT))
    assert taxonomy.counts["GMO / novel food"] == 352 + 103
    assert taxonomy.category_ids("GMO / novel food") == (26580, 26581)


def test_version_comes_from_the_file_name(tmp_path: Path) -> None:
    assert load_taxonomy(write(tmp_path, "v1-draft.csv", DRAFT)).version == "v1-draft"
    assert load_taxonomy(write(tmp_path, "v1.csv", DRAFT)).version == "1"


def test_a_row_without_label_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="21798"):
        load_taxonomy(write(tmp_path, "v1.csv", DRAFT.replace(",allergens\n", ",\n")))


def test_default_is_the_frozen_file_once_it_exists(tmp_path: Path) -> None:
    write(tmp_path, "v1-draft.csv", DRAFT)
    assert default_taxonomy_path(tmp_path).name == "v1-draft.csv"
    write(tmp_path, "v1.csv", DRAFT)
    assert default_taxonomy_path(tmp_path).name == "v1.csv"


def test_the_committed_draft_loads() -> None:
    taxonomy = load_taxonomy(default_taxonomy_path())
    assert "allergens" in taxonomy.labels
    assert taxonomy.labels[-1] == "other"
