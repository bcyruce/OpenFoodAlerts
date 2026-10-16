"""The harness: Labels + outputs -> the latest.json report (spec §7.3)."""

from pathlib import Path
from typing import Any

import pytest
from sklearn.metrics import cohen_kappa_score

from openfoodalerts.classify.input_hash import input_hash
from openfoodalerts.eval.cache import ModelOutput
from openfoodalerts.eval.files import ItemRow
from openfoodalerts.eval.harness import RunInput, build_report
from openfoodalerts.eval.labelset import Taxonomy, load_taxonomy
from openfoodalerts.eval.metrics import ABSTAIN

TAXONOMY = (
    "rasff_id,name_en,notifications_since_2020-01-01,label\n"
    "21801,pathogenic micro-organisms,6000,pathogenic micro-organisms\n"
    "21798,allergens,500,allergens\n"
    "21800,mycotoxins,400,mycotoxins\n"
    "21788,packaging defective / incorrect,6,other\n"
)
NOW = "2026-10-26T08:00:00+00:00"
MODEL, PROMPT = "fake-model", "v1"


@pytest.fixture
def taxonomy(tmp_path: Path) -> Taxonomy:
    path = tmp_path / "v1.csv"
    path.write_text(TAXONOMY, encoding="utf-8")
    return load_taxonomy(path)


def item(
    item_id: str,
    source: str,
    split: str = "dev",
    *,
    agreement: bool = False,
    official: tuple[str, ...] = (),
) -> ItemRow:
    return ItemRow(
        item_id=item_id,
        split=split,
        source=source,
        source_key=item_id,
        source_url="",
        published_on="",
        stratum="",
        noise_audit=source == "rasff",
        agreement=agreement,
        official_categories=official,
        input={"text": f"input of {item_id}"},
    )


def label(item_id: str, annotator: str = "A", **tasks: str) -> dict[str, str]:
    values = {
        "hazard_category": "unsure",
        "product_category": "unsure",
        "hazard": "",
        "origin_country": "",
        "product_type": "",
    } | tasks
    return {
        "item_id": item_id,
        "annotator": annotator,
        "guideline_version": "v1",
        **values,
        "note": "",
        "labelled_at": NOW,
    }


def pred(
    it: ItemRow,
    value: str | None,
    task: str = "hazard_category",
    confidence: str | None = "high",
    taxonomy_version: str = "1",
) -> ModelOutput:
    return ModelOutput(
        item_id=it.item_id,
        task=task,
        value=value,
        confidence=confidence if value is not None else None,
        abstained=value is None,
        evidence_span=None,
        input_hash=input_hash(
            it.input, prompt_version=PROMPT, model=MODEL, taxonomy_version=taxonomy_version
        ),
        model=MODEL,
        prompt_version=PROMPT,
        schema_version="1",
        taxonomy_version=taxonomy_version,
        created_at=NOW,
    )


def report(
    taxonomy: Taxonomy,
    items: list[ItemRow],
    labels: list[dict[str, str]],
    outputs: list[ModelOutput],
    split: str = "dev",
) -> dict[str, Any]:
    return build_report(
        items,
        labels,
        [RunInput(MODEL, PROMPT, "model", outputs)],
        taxonomy,
        split=split,
        git_sha="abc123",
        created_at=NOW,
    )


def test_without_labels_the_report_is_empty_but_complete(taxonomy: Taxonomy) -> None:
    items = [item("nv-1", "nvwa"), item("ra-1", "rasff", agreement=True)]
    out = report(taxonomy, items, [], [pred(items[0], "allergens")])
    assert out["git_sha"] == "abc123"
    assert out["created_at"] == NOW
    assert out["taxonomy_version"] == 1
    assert out["synthetic"] is False
    assert out["runs"] == []
    assert out["skipped"] == [
        {
            "model": MODEL,
            "prompt_version": PROMPT,
            "split": "dev",
            "task": "hazard_category",
            "reason": "no Labels",
        }
    ]
    assert out["agreement"]["cohens_kappa"] is None
    assert out["agreement"]["n"] == 0
    assert out["noise_audit"] == {
        "agreement_with_official": None,
        "n": 0,
        "n_unsure": 0,
        "n_unmapped": 0,
        "n_multi_label": 0,
    }
    assert out["label_status"] == {"dev": {"items": 2, "labelled": 0}}


def test_t1_is_scored_per_source_and_overall_with_abstentions_as_errors(
    taxonomy: Taxonomy,
) -> None:
    nv = [item(f"nv-{i}", "nvwa") for i in range(4)]
    fd = [item(f"fd-{i}", "openfda") for i in range(2)]
    ra = [item("ra-0", "rasff")]
    test_item = item("nv-9", "nvwa", "test")
    unsure = item("nv-8", "nvwa")
    items = [*nv, *fd, *ra, test_item, unsure]
    labels = [label(i.item_id, hazard_category="allergens") for i in nv]
    labels += [label(i.item_id, hazard_category="pathogenic micro-organisms") for i in fd]
    labels += [label("ra-0", hazard_category="mycotoxins")]
    labels += [label("nv-9", hazard_category="allergens"), label("nv-8")]
    preds = [
        pred(nv[0], "allergens"),
        pred(nv[1], "allergens", confidence="low"),
        pred(nv[2], None),  # abstained
        # nv[3]: no prediction (missing)
        pred(fd[0], "pathogenic micro-organisms"),
        pred(fd[1], "allergens", taxonomy_version="0"),  # made for another input: stale
        pred(ra[0], "mycotoxins", confidence="medium"),
        pred(test_item, "mycotoxins"),
    ]
    out = report(taxonomy, items, labels, preds)
    [run] = out["runs"]
    assert (run["model"], run["prompt_version"], run["kind"], run["split"], run["task"]) == (
        MODEL,
        PROMPT,
        "model",
        "dev",
        "hazard_category",
    )
    overall = run["overall"]
    # test item left out, unsure item left out and counted
    assert overall["n"] == 7
    assert overall["n_unsure"] == 1
    assert overall["accuracy"] == pytest.approx(4 / 7)
    assert overall["abstention_rate"] == pytest.approx(3 / 7)  # abstained, missing, stale
    assert overall["accuracy_answered"] == pytest.approx(1.0)
    assert (overall["n_missing"], overall["n_stale"]) == (1, 1)
    lo, hi = overall["macro_f1_ci95"]
    assert lo <= overall["macro_f1"] <= hi
    by_source = run["by_source"]
    assert {s: b["n"] for s, b in by_source.items()} == {"nvwa": 4, "openfda": 2, "rasff": 1}
    assert by_source["nvwa"]["accuracy"] == pytest.approx(2 / 4)
    assert by_source["openfda"]["accuracy"] == pytest.approx(1 / 2)
    assert by_source["rasff"]["macro_f1"] == pytest.approx(1.0)
    assert [p["n"] for p in overall["coverage_accuracy"]] == [2, 3, 4]
    assert run["per_class"]["allergens"]["support"] == 4
    cm = run["confusion_matrix"]
    # taxonomy order, abstain last
    assert cm["labels"] == ["pathogenic micro-organisms", "allergens", "mycotoxins", ABSTAIN]
    assert cm["matrix"][1] == [0, 2, 0, 2]


def test_the_test_split_is_scored_only_when_asked_for(taxonomy: Taxonomy) -> None:
    dev, test = item("nv-1", "nvwa"), item("nv-2", "nvwa", "test")
    labels = [label(i.item_id, hazard_category="allergens") for i in (dev, test)]
    preds = [pred(dev, "allergens"), pred(test, "mycotoxins")]
    assert report(taxonomy, [dev, test], labels, preds)["runs"][0]["overall"]["accuracy"] == 1.0
    [run] = report(taxonomy, [dev, test], labels, preds, split="test")["runs"]
    assert (run["split"], run["overall"]["accuracy"]) == ("test", 0.0)
    with pytest.raises(ValueError, match="split"):
        report(taxonomy, [dev], labels, preds, split="noise_audit")


def test_t2_to_t5_are_scored_on_nvwa_and_openfda_only(taxonomy: Taxonomy) -> None:
    nv, ra = item("nv-1", "nvwa"), item("ra-1", "rasff")
    labels = [label(i.item_id, product_category="cereals and bakery products") for i in (nv, ra)]
    preds = [pred(i, "cereals and bakery products", task="product_category") for i in (nv, ra)]
    [run] = report(taxonomy, [nv, ra], labels, preds)["runs"]
    assert run["task"] == "product_category"
    assert list(run["by_source"]) == ["nvwa", "openfda"]
    assert run["overall"]["n"] == 1


def test_t3_spans_exact_and_normalized(taxonomy: Taxonomy) -> None:
    its = [item(f"nv-{i}", "nvwa") for i in range(4)]
    labels = [
        label("nv-0", hazard="Listeria monocytogenes"),
        label("nv-1", hazard="melk"),
        label("nv-2", hazard="none"),
        label("nv-3", hazard="none"),
    ]
    preds = [
        pred(its[0], "Listeria monocytogenes", task="hazard"),
        pred(its[1], "Melk.", task="hazard"),
        pred(its[2], None, task="hazard"),  # abstention matches "none"
        pred(its[3], "glas", task="hazard"),
    ]
    [run] = report(taxonomy, its, labels, preds)["runs"]
    o = run["overall"]
    assert (o["n"], o["exact_match"], o["normalized_match"]) == (4, 0.5, 0.75)
    assert o["abstention_rate"] == 0.25
    assert "per_class" not in run and "confusion_matrix" not in run


def test_t4_countries_exact_and_iso2(taxonomy: Taxonomy) -> None:
    its = [item(f"fd-{i}", "openfda") for i in range(4)]
    labels = [
        label("fd-0", origin_country="GB"),
        label("fd-1", origin_country="NL"),
        label("fd-2", origin_country="unknown"),
        label("fd-3", origin_country="US"),
    ]
    preds = [
        pred(its[0], "UK", task="origin_country"),
        pred(its[1], "NL", task="origin_country"),
        pred(its[2], None, task="origin_country"),  # abstention = unknown
        pred(its[3], "MX", task="origin_country"),
    ]
    o = report(taxonomy, its, labels, preds)["runs"][0]["overall"]
    assert (o["exact_match"], o["normalized_match"]) == (0.5, 0.75)


def test_t5_product_type_has_a_confusion_matrix_in_product_type_order(
    taxonomy: Taxonomy,
) -> None:
    its = [item(f"nv-{i}", "nvwa") for i in range(3)]
    labels = [label("nv-0", product_type="food"), label("nv-1", product_type="feed")]
    labels.append(label("nv-2", product_type="food"))
    preds = [pred(its[0], "food", task="product_type"), pred(its[1], "food", task="product_type")]
    preds.append(pred(its[2], "food contact material", task="product_type"))
    [run] = report(taxonomy, its, labels, preds)["runs"]
    assert run["overall"]["accuracy"] == pytest.approx(1 / 3)
    cm = run["confusion_matrix"]
    assert cm["labels"] == ["food", "feed", "food contact material", ABSTAIN]
    assert cm["matrix"][0] == [1, 0, 1, 0]


def test_agreement_uses_both_annotators_latest_labels_on_the_subset(taxonomy: Taxonomy) -> None:
    its = [item(f"nv-{i}", "nvwa", "dev" if i % 2 else "test", agreement=True) for i in range(6)]
    its.append(item("nv-9", "nvwa"))  # not in the subset
    a_values = ["allergens", "allergens", "mycotoxins", "mycotoxins", "other", "allergens"]
    b_values = ["allergens", "mycotoxins", "mycotoxins", "mycotoxins", "other", "unsure"]
    labels = [label(f"nv-{i}", hazard_category=v) for i, v in enumerate(a_values)]
    labels += [label(f"nv-{i}", "B", hazard_category=v) for i, v in enumerate(b_values)]
    labels += [label("nv-9", hazard_category="allergens"), label("nv-9", "B", hazard_category="x")]
    agreement = report(taxonomy, its, labels, [])["agreement"]
    # both splits count; B's "unsure" pair is left out
    assert agreement["n"] == 5
    assert agreement["subset_size"] == 6
    assert agreement["cohens_kappa"] == pytest.approx(cohen_kappa_score(a_values[:5], b_values[:5]))
    assert agreement["by_task"]["product_type"] == {"cohens_kappa": None, "n": 0}


def test_noise_audit_compares_a_with_the_official_categories(taxonomy: Taxonomy) -> None:
    its = [
        item("ra-1", "rasff", official=("allergens",)),
        item("ra-2", "rasff", "test", official=("pathogenic micro-organisms",)),
        item("ra-3", "rasff", official=("allergens", "mycotoxins")),  # two labels
        item("ra-4", "rasff", official=("packaging defective / incorrect",)),  # -> other
        item("ra-5", "rasff", official=("no such category",)),
        item("ra-6", "rasff", official=("allergens",)),
    ]
    labels = [
        label("ra-1", hazard_category="allergens"),
        label("ra-2", hazard_category="allergens"),
        label("ra-3", hazard_category="mycotoxins"),
        label("ra-4", hazard_category="other"),
        label("ra-5", hazard_category="other"),
        label("ra-6"),  # unsure
    ]
    audit = report(taxonomy, its, labels, [])["noise_audit"]
    assert audit == {
        "agreement_with_official": pytest.approx(3 / 4),
        "n": 4,
        "n_unsure": 1,
        "n_unmapped": 1,
        "n_multi_label": 1,
    }
