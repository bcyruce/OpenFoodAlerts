"""The committed T6 prompts: one per language, examples that pass the code checks and are
not eval items."""

import json

import pytest

from openfoodalerts.classify.prompts import default_prompts_dir, load_prompt
from openfoodalerts.classify.summary import SUMMARY_TASKS, SummaryTask
from openfoodalerts.eval.files import read_items
from openfoodalerts.eval.job import default_eval_dir


@pytest.mark.parametrize("task_name", SUMMARY_TASKS)
def test_each_language_has_a_v1_prompt_whose_examples_pass_the_checks(task_name: str) -> None:
    task = SummaryTask(task_name.removeprefix("summary_"))
    prompt = load_prompt(task_name, "v1")
    assert prompt.path == default_prompts_dir() / task_name / "v1.md"
    assert 5 <= len(prompt.examples) <= 12
    eval_inputs = {
        json.dumps(i.input, sort_keys=True) for i in read_items(default_eval_dir() / "items.csv")
    }
    for n, example in enumerate(prompt.examples, start=1):
        assert example.source in task.sources, n
        assert json.dumps(example.input, sort_keys=True) not in eval_inputs, n
        assert list(example.output) == ["abstain", "summary", "confidence"], n
        verdict = task.check(example.output, example.input)
        if example.output["abstain"]:
            assert verdict.abstain_reason == "model_abstained", n
            assert example.output["summary"] == "", n
        else:
            assert not verdict.abstained, (n, verdict.abstain_reason)
    assert {e.source for e in prompt.examples} == set(task.sources)
    assert any(e.output["abstain"] for e in prompt.examples)
    # the fixed prefix is long enough for prompt caching (Haiku 5.5: 512 tokens)
    assert len(prompt.system) > 3000
