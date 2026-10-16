"""T1 baselines: keyword rules and TF-IDF + LogisticRegression trained on the silver set."""

from pathlib import Path

import pytest

from openfoodalerts.classify.input_hash import input_hash
from openfoodalerts.eval.baselines import (
    KEYWORD_MODEL,
    TFIDF_MODEL,
    InsufficientTraining,
    keyword_outputs,
    read_silver,
    tfidf_outputs,
)
from openfoodalerts.eval.files import ItemRow
from openfoodalerts.eval.labelset import Taxonomy, default_taxonomy_path, load_taxonomy
from openfoodalerts.eval.metrics import CONFIDENCES

NOW = "2026-10-26T08:00:00+00:00"


@pytest.fixture(scope="module")
def taxonomy() -> Taxonomy:
    return load_taxonomy(default_taxonomy_path())


def item(item_id: str, source: str = "openfda", **snapshot: str) -> ItemRow:
    return ItemRow(
        item_id=item_id,
        split="dev",
        source=source,
        source_key=item_id,
        source_url="",
        published_on="",
        stratum="",
        noise_audit=False,
        agreement=False,
        official_categories=(),
        input=snapshot,
    )


def test_keyword_baseline_maps_the_rule_to_a_label_with_its_evidence(
    taxonomy: Taxonomy,
) -> None:
    items = [
        item("fd-1", product_description="Cookies", reason_for_recall="Contains undeclared milk"),
        # only the product description matches: weaker evidence
        item("fd-2", product_description="Salmonella test kit", reason_for_recall="Recalled"),
        item("fd-3", product_description="Bread", reason_for_recall="Wrong weight"),
        # rule category "poor or insufficient controls" is folded into "other" in v1 draft
        item("fd-4", product_description="Juice", reason_for_recall="Not pasteurized"),
    ]
    preds = {p.item_id: p for p in keyword_outputs(items, taxonomy, created_at=NOW)}
    assert (preds["fd-1"].value, preds["fd-1"].confidence) == ("allergens", "high")
    assert preds["fd-1"].evidence_span == "undeclared milk"
    assert (preds["fd-2"].value, preds["fd-2"].confidence) == (
        "pathogenic micro-organisms",
        "medium",
    )
    assert preds["fd-3"].abstained and preds["fd-3"].value is None
    assert preds["fd-3"].confidence is None
    assert preds["fd-4"].value == "other"
    p = preds["fd-1"]
    assert (p.model, p.task, p.taxonomy_version) == (
        KEYWORD_MODEL,
        "hazard_category",
        taxonomy.version,
    )
    assert p.input_hash == input_hash(
        items[0].input,
        prompt_version=p.prompt_version,
        model=KEYWORD_MODEL,
        taxonomy_version=taxonomy.version,
    )


SILVER = [
    ("Listeria monocytogenes in smoked salmon", "pathogenic micro-organisms"),
    ("Salmonella in chicken meat", "pathogenic micro-organisms"),
    ("Salmonella Enteritidis in eggs", "pathogenic micro-organisms"),
    ("Listeria in cheese", "pathogenic micro-organisms"),
    ("Aflatoxins in pistachios", "mycotoxins"),
    ("Aflatoxin B1 in peanuts", "mycotoxins"),
    ("Ochratoxin A in raisins", "mycotoxins"),
    ("Aflatoxins in dried figs", "mycotoxins"),
    ("Undeclared milk in chocolate", "allergens"),
    ("Undeclared peanut in biscuits", "allergens"),
    ("Undeclared gluten in noodles", "allergens"),
    ("Undeclared sesame in bread", "allergens"),
]


def test_tfidf_baseline_learns_from_silver_and_never_abstains(taxonomy: Taxonomy) -> None:
    items = [
        item("ra-1", "rasff", subject="Listeria monocytogenes in frozen corn"),
        item("ra-2", "rasff", subject="Aflatoxins in hazelnuts from Turkey"),
        item("nv-1", "nvwa", title="Undeclared milk in dark chocolate", summary="", products=""),
    ]
    preds = tfidf_outputs(items, SILVER, taxonomy, created_at=NOW)
    assert [p.value for p in preds] == [
        "pathogenic micro-organisms",
        "mycotoxins",
        "allergens",
    ]
    assert all(not p.abstained and p.confidence in CONFIDENCES for p in preds)
    assert all(p.model == TFIDF_MODEL for p in preds)
    # deterministic: training again gives the same outputs and confidences
    assert tfidf_outputs(items, SILVER, taxonomy, created_at=NOW) == preds


def test_tfidf_baseline_needs_two_labels_in_the_silver_set(taxonomy: Taxonomy) -> None:
    with pytest.raises(InsufficientTraining):
        tfidf_outputs([item("ra-1", "rasff", subject="x")], SILVER[:4], taxonomy, created_at=NOW)


def test_silver_rows_outside_the_label_set_are_dropped(tmp_path: Path, taxonomy: Taxonomy) -> None:
    path = tmp_path / "silver.csv"
    path.write_text(
        "source_key,published_on,label,rasff_categories,subject\n"
        "2026.1,2026-10-22,mycotoxins,mycotoxins,Aflatoxins in figs\n"
        "2026.2,2026-10-22,no such label,x,Something\n",
        encoding="utf-8",
    )
    assert read_silver(path, taxonomy) == [("Aflatoxins in figs", "mycotoxins")]
    assert read_silver(tmp_path / "missing.csv", taxonomy) == []
