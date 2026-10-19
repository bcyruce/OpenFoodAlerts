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
    # 4 T1 outputs + 5 T6 summaries (fd-1 en/nl, nv-1 en/nl/zh; see test_summary_eval.py)
    assert written == {tmp_path / "fake" / "v1.jsonl": 4 + 5}
    [run] = read_cache(tmp_path)
    outputs = [o for o in run.outputs if o.task == "hazard_category"]
    by_id = {o.item_id: o for o in outputs}
    assert by_id["fd-1"].value == "pathogenic micro-organisms"
    assert by_id["nv-1"].value == "foreign bodies"
    assert by_id["ra-1"].value == "mycotoxins"  # RASFF is scored on its subject
    assert by_id["ra-2"].abstained and by_id["ra-2"].value is None
    taxonomy = load_taxonomy(default_taxonomy_path())
    for output in outputs:
        assert (output.model, output.prompt_version, output.schema_version) == ("fake", "v1", "1")
        assert output.taxonomy_version == taxonomy.version
        source_item = next(i for i in ITEMS if i.item_id == output.item_id)
        assert output.input_hash == input_hash(
            source_item.input, prompt_version="v1", model="fake", taxonomy_version=taxonomy.version
        )


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
