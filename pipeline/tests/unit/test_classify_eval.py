"""`make eval-refresh`: the registered classifiers write eval/cache/{model}/{prompt}.jsonl."""

from pathlib import Path

import pytest

from openfoodalerts.classify.eval_adapter import eval_outputs
from openfoodalerts.classify.fake import KeywordClassifier
from openfoodalerts.classify.input_hash import input_hash
from openfoodalerts.classify.model import ClassifierUnavailable, ModelRequest, ModelResponse
from openfoodalerts.classify.prompts import load_prompt
from openfoodalerts.classify.registry import make_classifier
from openfoodalerts.classify.tasks import HazardCategoryTask
from openfoodalerts.eval.cache import read_cache
from openfoodalerts.eval.files import ItemRow
from openfoodalerts.eval.harness import RunInput, build_report
from openfoodalerts.eval.labelset import default_taxonomy_path, load_taxonomy
from openfoodalerts.eval.refresh import CLASSIFIERS, refresh_cache

NOW = "2026-10-26T08:00:00+00:00"


def item(item_id: str, source: str, split: str = "dev", **snapshot: str) -> ItemRow:
    return ItemRow(item_id, split, source, item_id, "", "", "", False, False, (), snapshot)


ITEMS = [
    item("fd-1", "openfda", product_description="Brie", reason_for_recall="Listeria found."),
    item("nv-1", "nvwa", title="Waarschuwing", summary="Bevat glasdeeltjes.", products=""),
    item("ra-1", "rasff", subject="Aflatoxins in figs"),
    item("ra-2", "rasff", subject="2026.0001"),
    item("fd-2", "openfda", "test", product_description="X", reason_for_recall="Salmonella"),
]


def test_both_models_are_registered_for_eval_refresh() -> None:
    assert {"claude-haiku-5-5", "fake"} <= set(CLASSIFIERS)


def test_the_fake_model_refreshes_the_dev_cache_through_the_whole_path(tmp_path: Path) -> None:
    written = refresh_cache(ITEMS, split="dev", cache_dir=tmp_path, models=["fake"])
    # T1 on the 4 dev items, T2-T5 on the 2 NVWA / openFDA ones
    assert written == {tmp_path / "fake" / "v1.jsonl": 4 + 4 * 2}
    [run] = read_cache(tmp_path)
    t1 = [o for o in run.outputs if o.task == "hazard_category"]
    by_id = {o.item_id: o for o in t1}
    assert by_id["fd-1"].value == "pathogenic micro-organisms"
    assert by_id["nv-1"].value == "foreign bodies"
    assert by_id["ra-1"].value == "mycotoxins"  # RASFF is scored on its subject
    assert by_id["ra-2"].abstained and by_id["ra-2"].value is None
    taxonomy = load_taxonomy(default_taxonomy_path())
    for output in t1:
        assert (output.model, output.prompt_version, output.schema_version) == ("fake", "v1", "1")
        assert output.taxonomy_version == taxonomy.version
        source_item = next(i for i in ITEMS if i.item_id == output.item_id)
        assert output.input_hash == input_hash(
            source_item.input, prompt_version="v1", model="fake", taxonomy_version=taxonomy.version
        )


def label(item_id: str, **values: str) -> dict[str, str]:
    empty = dict.fromkeys(
        ("hazard_category", "product_category", "hazard", "origin_country", "product_type"), ""
    )
    return {"item_id": item_id, "annotator": "A", "guideline_version": "v1", "note": "",
            "labelled_at": NOW} | empty | values  # fmt: skip


def test_make_eval_scores_t2_to_t5_from_the_refreshed_cache(tmp_path: Path) -> None:
    items = [
        item("fd-1", "openfda", product_description="Pecorino cheese. Product of Italy.",
             reason_for_recall="Potential Listeria contamination"),
        item("nv-1", "nvwa", title="Waarschuwing kaas",
             summary="Bevat glasdeeltjes. Eet de kaas niet.", products=""),
        item("nv-2", "nvwa", title="Waarschuwing", summary="Breng het terug.", products=""),
    ]  # fmt: skip
    refresh_cache(items, split="dev", cache_dir=tmp_path, models=["fake"])
    [run] = read_cache(tmp_path)
    t3 = {o.item_id: o for o in run.outputs if o.task == "hazard"}
    assert t3["fd-1"].value == "Listeria" and t3["fd-1"].taxonomy_version == ""
    labels = [  # synthetic Labels: the fake model is right on fd-1 and nv-1
        label("fd-1", product_category="milk and milk products", hazard="Listeria",
              origin_country="IT", product_type="food"),
        label("nv-1", product_category="milk and milk products", hazard="glasdeeltjes",
              origin_country="unknown", product_type="food"),
        label("nv-2", product_category="other food product / mixed", hazard="none",
              origin_country="unknown", product_type="non-food"),
    ]  # fmt: skip
    report = build_report(
        items, labels, [RunInput("fake", "v1", "model", run.outputs)],
        load_taxonomy(default_taxonomy_path()), split="dev", git_sha="x", created_at=NOW,
    )  # fmt: skip
    runs = {r["task"]: r["overall"] for r in report["runs"]}
    assert set(runs) == {"product_category", "hazard", "origin_country", "product_type"}
    for overall in runs.values():
        assert (overall["n"], overall["n_stale"], overall["n_missing"]) == (3, 0, 0)
    # nv-2: the fake abstains on T2 (wrong), T3 (right: Label none) and T5 (wrong)
    assert runs["product_category"]["accuracy"] == pytest.approx(2 / 3)
    assert runs["hazard"]["exact_match"] == 1.0
    assert runs["origin_country"]["exact_match"] == 1.0
    assert runs["product_type"]["accuracy"] == pytest.approx(2 / 3)


def test_claude_without_a_key_fails_before_any_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ClassifierUnavailable, match="ANTHROPIC_API_KEY"):
        refresh_cache(ITEMS, split="dev", cache_dir=tmp_path, models=["claude-haiku-5-5"])
    assert not (tmp_path / "claude-haiku-5-5").exists()


class Counting:
    model = "counting"

    def __init__(self) -> None:
        self.calls = 0
        self.fake = KeywordClassifier(load_taxonomy(default_taxonomy_path()))

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        return self.fake.complete(request)


def test_identical_inputs_are_sent_once() -> None:
    twins = [
        item("fd-1", "openfda", reason_for_recall="Listeria"),
        item("fd-2", "openfda", reason_for_recall="Listeria"),
    ]
    model = Counting()
    task = HazardCategoryTask(load_taxonomy(default_taxonomy_path()))
    outputs = eval_outputs(
        twins, task=task, prompt=load_prompt(task.name), classifier=model, created_at=NOW
    )
    assert model.calls == 1
    assert [o.item_id for o in outputs] == ["fd-1", "fd-2"]
    assert outputs[0].value == outputs[1].value == "pathogenic micro-organisms"


def test_unknown_models_are_unavailable() -> None:
    with pytest.raises(ClassifierUnavailable, match="unknown model"):
        make_classifier("gpt-5-mini", load_taxonomy(default_taxonomy_path()))
