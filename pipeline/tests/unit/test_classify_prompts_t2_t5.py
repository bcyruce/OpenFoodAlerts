"""The committed T2-T5 prompts: lists match the task's choices, examples pass the task's
own checks and are not eval items."""

import json

import pytest

from openfoodalerts.classify.prompts import load_prompt
from openfoodalerts.classify.tasks import make_task
from openfoodalerts.classify.tasks_t2_t5 import product_category_names
from openfoodalerts.eval.files import read_items
from openfoodalerts.eval.job import default_eval_dir
from openfoodalerts.eval.labelset import default_taxonomy_path, load_taxonomy

TASKS = ("product_category", "hazard", "origin_country", "product_type")


def test_the_lists_in_the_prompts_are_the_tasks_choices() -> None:
    assert load_prompt("product_category", "v1").categories == product_category_names()
    assert len(product_category_names()) == 37
    assert load_prompt("product_type", "v1").categories == (
        "food",
        "feed",
        "food contact material",
        "non-food",
    )
    # T3 and T4 have no list in the prompt (T4's country codes are the schema's enum)
    assert load_prompt("hazard", "v1").categories == ()
    assert load_prompt("origin_country", "v1").categories == ()


@pytest.mark.parametrize("name", TASKS)
def test_every_example_passes_the_tasks_check_and_is_not_an_eval_item(name: str) -> None:
    task = make_task(name, load_taxonomy(default_taxonomy_path()))
    prompt = load_prompt(name, "v1")
    assert "DRAFT, owner to review" in prompt.path.read_text(encoding="utf-8")
    assert "DRAFT" not in prompt.system  # maintainer notes are not sent
    assert 10 <= len(prompt.examples) <= 15
    eval_inputs = {
        json.dumps(i.input, sort_keys=True) for i in read_items(default_eval_dir() / "items.csv")
    }
    required = task.output_schema()["required"]
    answers = []
    for n, example in enumerate(prompt.examples, start=1):
        assert example.source in ("nvwa", "openfda"), n
        assert json.dumps(example.input, sort_keys=True) not in eval_inputs, n
        assert list(example.output) == required, n
        verdict = task.check(example.output, example.input)
        if verdict.abstained:
            assert verdict.abstain_reason == "model_abstained", n
        answers.append(verdict.category)
    assert {e.source for e in prompt.examples} == {"nvwa", "openfda"}
    assert None in answers or name == "origin_country"  # an abstain example (T4: unknown)
    assert len(set(answers)) >= 4
