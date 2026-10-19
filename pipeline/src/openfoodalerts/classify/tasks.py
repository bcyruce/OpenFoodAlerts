"""AI classification tasks (spec §6.1). T1 hazard_category is the first; T2-T6 add one
class each with the same shape (see `Task`).

A task owns everything that is specific to it:

- its scope: the Sources it runs on in production (`sources`) and the Sources of the eval
  items it is scored on (`eval_sources`);
- the model input: `build_input` makes the input snapshot from a Notification row with the
  eval snapshot definitions (`eval.snapshot`), so production and eval inputs are the same,
  and `render_input` turns it into the user message;
- the output contract: `output_schema` (a JSON schema for structured output, enum + abstain
  where the task has a fixed list) and `check`, which validates a model output in code and
  turns anything that fails into an abstain with a reason (ADR 0006);
- its versions: `schema_version` (the output schema's structure) and `taxonomy_version`
  (the label set in the enum, None for tasks without one).

The prompt (`prompts/{task}/vN.md`) and the model are not part of the task.
"""

import json
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from openfoodalerts.classify.evidence import find_evidence
from openfoodalerts.eval.labelset import Taxonomy
from openfoodalerts.eval.snapshot import input_snapshot

ABSTAIN = "abstain"
CONFIDENCES = ("high", "medium", "low")

# Why a result is an abstain (stored in value.abstain_reason):
MODEL_ABSTAINED = "model_abstained"  # the model chose abstain
EVIDENCE_NOT_IN_INPUT = "evidence_not_in_input"  # evidence_span failed the substring check
INVALID_OUTPUT = "invalid_output"  # not the schema (missing key, value outside the enum)
REFUSAL = "refusal"  # the model declined the request (stop_reason "refusal")
TRUNCATED = "truncated"  # the output hit max_tokens before it was complete


@dataclass(frozen=True)
class Verdict:
    """A validated model output: what is stored and scored."""

    # the task's output value as text (T1: the category), None when abstained
    category: str | None
    confidence: str | None
    abstained: bool
    evidence_span: str | None
    abstain_reason: str | None
    # ai_classifications.value
    value: dict[str, Any]


class Task(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def schema_version(self) -> str: ...
    @property
    def taxonomy_version(self) -> str | None: ...
    @property
    def sources(self) -> tuple[str, ...]: ...
    @property
    def eval_sources(self) -> tuple[str, ...]: ...

    def build_input(self, source: str, row: Mapping[str, Any]) -> dict[str, str]: ...
    def render_input(self, source: str, snapshot: Mapping[str, str]) -> str: ...
    def output_schema(self) -> dict[str, Any]: ...
    def check(
        self, output: object, snapshot: Mapping[str, str], *, failure: str | None = None
    ) -> Verdict: ...


def nfc_snapshot(snapshot: Mapping[str, str]) -> dict[str, str]:
    """The snapshot as sent to the model: NFC, as in `input_hash`, nothing else changed."""
    return {key: unicodedata.normalize("NFC", value) for key, value in snapshot.items()}


def abstain(reason: str, output: object) -> Verdict:
    return Verdict(
        category=None,
        confidence=None,
        abstained=True,
        evidence_span=None,
        abstain_reason=reason,
        value={"category": None, "abstain_reason": reason, "model_output": output},
    )


class HazardCategoryTask:
    """T1: the Primary hazard category, one taxonomy label or abstain (spec §6.1, §6.2)."""

    name = "hazard_category"
    schema_version = "1"
    sources = ("nvwa", "openfda")
    # RASFF is scored too, on its subject only (silver / noise-audit items), never classified
    # in production: it has official Hazard categories.
    eval_sources = ("rasff", "nvwa", "openfda")

    def __init__(self, taxonomy: Taxonomy) -> None:
        self.taxonomy = taxonomy

    @property
    def taxonomy_version(self) -> str:
        return self.taxonomy.version

    def build_input(self, source: str, row: Mapping[str, Any]) -> dict[str, str]:
        return input_snapshot(source, row)

    def render_input(self, source: str, snapshot: Mapping[str, str]) -> str:
        # Same layout as the "Input:" lines of the prompt's examples.
        return json.dumps({"source": source, "input": nfc_snapshot(snapshot)}, ensure_ascii=False)

    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "evidence_span": {
                    "type": "string",
                    "description": "Verbatim passage of one input field that shows the "
                    "category; empty when abstaining.",
                },
                "category": {"type": "string", "enum": [*self.taxonomy.labels, ABSTAIN]},
                "confidence": {"type": "string", "enum": list(CONFIDENCES)},
            },
            "required": ["evidence_span", "category", "confidence"],
            "additionalProperties": False,
        }

    def check(
        self, output: object, snapshot: Mapping[str, str], *, failure: str | None = None
    ) -> Verdict:
        if output is None:
            return abstain(failure or INVALID_OUTPUT, None)
        if not isinstance(output, Mapping):
            return abstain(INVALID_OUTPUT, output)
        out = dict(output)
        category, confidence, span = (
            out.get("category"),
            out.get("confidence"),
            out.get("evidence_span"),
        )
        if not isinstance(span, str) or confidence not in CONFIDENCES:
            return abstain(INVALID_OUTPUT, out)
        if category == ABSTAIN:
            return abstain(MODEL_ABSTAINED, out)
        if category not in self.taxonomy.labels:
            return abstain(INVALID_OUTPUT, out)
        if find_evidence(span, snapshot) is None:
            return abstain(EVIDENCE_NOT_IN_INPUT, out)
        return Verdict(
            category=str(category),
            confidence=str(confidence),
            abstained=False,
            evidence_span=span.strip(),
            abstain_reason=None,
            value={"category": category},
        )


def make_task(name: str, taxonomy: Taxonomy) -> Task:
    if name == HazardCategoryTask.name:
        return HazardCategoryTask(taxonomy)
    from openfoodalerts.classify.summary import SUMMARY_TASKS, SummaryTask  # T6, ticket 18

    if name in SUMMARY_TASKS:
        return SummaryTask(name.removeprefix("summary_"))
    raise ValueError(f"unknown or not yet implemented task {name!r}")
