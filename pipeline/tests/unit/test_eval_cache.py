"""Model output cache: eval/cache/{model}/{prompt_version}.jsonl, and the input hash."""

import json
from pathlib import Path

import pytest

from openfoodalerts.classify.input_hash import input_hash
from openfoodalerts.eval.cache import CacheError, ModelOutput, read_cache, write_outputs

INPUT = {"product_description": "Peanut butter 340 g", "reason_for_recall": "Salmonella"}


def _pred(item_id: str, task: str = "hazard_category", **kw: object) -> ModelOutput:
    values: dict[str, object] = {
        "item_id": item_id,
        "task": task,
        "value": "pathogenic micro-organisms",
        "confidence": "high",
        "abstained": False,
        "evidence_span": "Salmonella",
        "input_hash": "h-" + item_id,
        "model": "claude-haiku-5-5",
        "prompt_version": "v1",
        "schema_version": "1",
        "taxonomy_version": "1",
        "created_at": "2026-10-26T08:00:00+00:00",
    }
    values.update(kw)
    return ModelOutput(**values)  # type: ignore[arg-type]


def test_input_hash_depends_on_input_prompt_model_and_taxonomy() -> None:
    h = input_hash(INPUT, prompt_version="v1", model="claude-haiku-5-5", taxonomy_version="1")
    assert h == input_hash(
        dict(INPUT), prompt_version="v1", model="claude-haiku-5-5", taxonomy_version="1"
    )
    assert len(h) == 64
    others = [
        input_hash(
            {**INPUT, "reason_for_recall": "Listeria"},
            prompt_version="v1",
            model="claude-haiku-5-5",
            taxonomy_version="1",
        ),
        input_hash(INPUT, prompt_version="v2", model="claude-haiku-5-5", taxonomy_version="1"),
        input_hash(INPUT, prompt_version="v1", model="gpt-5-mini", taxonomy_version="1"),
        input_hash(INPUT, prompt_version="v1", model="claude-haiku-5-5", taxonomy_version="2"),
    ]
    assert h not in others
    # frozen: changing the canonical form invalidates every cache and ai_classification
    # sha256 of '{"product_description":"Peanut butter 340 g","reason_for_recall":"Salmonella"}'
    # + "\nv1\nclaude-haiku-5-5\n1"
    assert h == "a1cb321a95d83211997c2876502b822e64d61a289dcb9465f5d0994d6f5d96e6"


def test_write_then_read_round_trips_one_file_per_model_and_prompt(tmp_path: Path) -> None:
    preds = [_pred("nv-00000002"), _pred("nv-00000001"), _pred("nv-00000001", "product_type")]
    path = write_outputs(tmp_path, preds)
    assert path == tmp_path / "claude-haiku-5-5" / "v1.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    # sorted by task, then item: rewriting gives the same bytes
    assert [json.loads(line)["item_id"] for line in lines] == [
        "nv-00000001",
        "nv-00000002",
        "nv-00000001",
    ]
    assert list(json.loads(lines[0])) == [
        "item_id",
        "task",
        "value",
        "confidence",
        "abstained",
        "evidence_span",
        "input_hash",
        "model",
        "prompt_version",
        "schema_version",
        "taxonomy_version",
        "created_at",
    ]
    [cached] = read_cache(tmp_path)
    assert (cached.model, cached.prompt_version) == ("claude-haiku-5-5", "v1")
    assert sorted(cached.outputs, key=lambda p: (p.task, p.item_id)) == sorted(
        preds, key=lambda p: (p.task, p.item_id)
    )


def test_writing_again_replaces_the_same_item_and_task_and_keeps_the_rest(
    tmp_path: Path,
) -> None:
    write_outputs(tmp_path, [_pred("nv-00000001"), _pred("nv-00000002")])
    write_outputs(tmp_path, [_pred("nv-00000001", value=None, abstained=True)])
    [cached] = read_cache(tmp_path)
    by_item = {p.item_id: p for p in cached.outputs}
    assert by_item["nv-00000001"].abstained
    assert not by_item["nv-00000002"].abstained


def test_a_file_mixing_models_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="one model and prompt version"):
        write_outputs(tmp_path, [_pred("nv-1"), _pred("nv-2", model="gpt-5-mini")])


def test_invalid_lines_name_the_file_and_line(tmp_path: Path) -> None:
    path = write_outputs(tmp_path, [_pred("nv-00000001")])
    good = path.read_text(encoding="utf-8")
    bad = json.loads(good)
    bad["model"] = "someone-else"
    path.write_text(good + json.dumps(bad) + "\n", encoding="utf-8")
    with pytest.raises(CacheError, match=r"v1\.jsonl:2"):
        read_cache(tmp_path)
    bad = json.loads(good) | {"confidence": "very"}
    path.write_text(json.dumps(bad) + "\n", encoding="utf-8")
    with pytest.raises(CacheError, match=r"v1\.jsonl:1.*confidence"):
        read_cache(tmp_path)
    path.write_text("{not json\n", encoding="utf-8")
    with pytest.raises(CacheError, match=r"v1\.jsonl:1"):
        read_cache(tmp_path)


def test_an_absent_cache_directory_is_empty(tmp_path: Path) -> None:
    assert read_cache(tmp_path / "missing") == []
