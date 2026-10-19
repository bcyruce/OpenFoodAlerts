"""Prompt files `prompts/{task}/vN.md`: versioning, the cacheable text, the committed T1 prompt."""

import json
from pathlib import Path

import pytest

from openfoodalerts.classify.evidence import find_evidence
from openfoodalerts.classify.prompts import (
    PromptError,
    default_prompts_dir,
    latest_version,
    load_prompt,
)
from openfoodalerts.eval.files import read_items
from openfoodalerts.eval.job import default_eval_dir
from openfoodalerts.eval.labelset import default_taxonomy_path, load_taxonomy

PROMPT = """<!--
notes for maintainers
-->
You classify things.

## Categories

- `allergens`: undeclared allergens.
- `other`: anything else.

## Examples

Example 1
Input: {"source": "rasff", "input": {"subject": "Peanut in cookies"}}
Output: {"evidence_span": "Peanut", "category": "allergens", "confidence": "high"}
"""


def write(directory: Path, name: str, text: str = PROMPT) -> Path:
    path = directory / "hazard_category" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def test_the_version_is_the_file_name_and_the_newest_is_the_default(tmp_path: Path) -> None:
    for name in ("v1.md", "v2.md", "v10.md", "notes.md"):
        write(tmp_path, name)
    assert latest_version("hazard_category", tmp_path) == "v10"
    assert load_prompt("hazard_category", directory=tmp_path).version == "v10"
    assert load_prompt("hazard_category", "v2", directory=tmp_path).version == "v2"
    with pytest.raises(PromptError, match="no prompt"):
        load_prompt("product_category", directory=tmp_path)


def test_the_maintainer_comment_is_not_sent_and_the_text_is_parsed(tmp_path: Path) -> None:
    write(tmp_path, "v1.md")
    prompt = load_prompt("hazard_category", directory=tmp_path)
    assert prompt.task == "hazard_category"
    assert prompt.system.startswith("You classify things.")
    assert "maintainers" not in prompt.system
    assert prompt.categories == ("allergens", "other")
    [example] = prompt.examples
    assert example.source == "rasff"
    assert example.input == {"subject": "Peanut in cookies"}
    assert example.output == {
        "evidence_span": "Peanut",
        "category": "allergens",
        "confidence": "high",
    }


def test_an_example_whose_output_is_not_json_is_an_error(tmp_path: Path) -> None:
    write(tmp_path, "v1.md", PROMPT.replace('"confidence": "high"}', '"confidence": high}'))
    with pytest.raises(PromptError, match="example 1"):
        load_prompt("hazard_category", directory=tmp_path)


# The committed prompt ------------------------------------------------------------------


def test_the_committed_t1_prompt_lists_exactly_the_taxonomy_labels() -> None:
    taxonomy = load_taxonomy(default_taxonomy_path())
    prompt = load_prompt("hazard_category", "v1")
    assert prompt.path == default_prompts_dir() / "hazard_category" / "v1.md"
    assert prompt.categories == taxonomy.labels


def test_the_committed_t1_examples_are_valid_and_are_not_eval_items() -> None:
    taxonomy = load_taxonomy(default_taxonomy_path())
    prompt = load_prompt("hazard_category", "v1")
    assert 10 <= len(prompt.examples) <= 15
    items = read_items(default_eval_dir() / "items.csv")
    eval_inputs = {json.dumps(i.input, sort_keys=True) for i in items}
    for n, example in enumerate(prompt.examples, start=1):
        assert json.dumps(example.input, sort_keys=True) not in eval_inputs, n
        out = example.output
        assert list(out) == ["evidence_span", "category", "confidence"], n
        assert out["confidence"] in ("high", "medium", "low"), n
        if out["category"] == "abstain":
            assert out["evidence_span"] == "", n
        else:
            assert out["category"] in taxonomy.labels, n
            assert find_evidence(out["evidence_span"], example.input) is not None, n
    assert {e.source for e in prompt.examples} == {"rasff", "nvwa", "openfda"}
    assert any(e.output["category"] == "abstain" for e in prompt.examples)
