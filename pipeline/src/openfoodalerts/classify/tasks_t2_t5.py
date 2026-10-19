"""T2-T5 (spec §6.1): the same `Task` shape as T1 (`tasks.HazardCategoryTask`).

Values (`ai_classifications.value`) when not abstained:

- T2 `product_category`: `{"category": "<RASFF Product category name>"}`, a name from
  db/seed/rasff/product_categories.json, with a verbatim evidence span;
- T3 `hazard`: `{"hazard": "<span>"}`, the Hazard as the input words it, found in one
  input field (stored with whitespace collapsed; also the evidence span);
- T4 `origin_country`: `{"country": "<ISO2>"}` with a verbatim span that states the
  origin, or `{"country": "unknown"}` without one;
- T5 `product_type`: `{"product_type": "food"}` (or feed, food contact material,
  non-food) with a verbatim evidence span.

An abstained row's value is `{"<key>": null, "abstain_reason": ..., "model_output": ...}`,
as for T1 (`tasks.abstain`). `unknown` is T4's answer for "the text does not state an
origin", not an abstain: it has a confidence and is scored as a value (the eval treats an
abstain as `unknown` too, spec §7.2). The tasks have no taxonomy (`taxonomy_version` None);
their fixed lists (RASFF Product categories, countries, Product types) are part of the
prompt and schema, so a change means a new prompt version.

All four read the same input snapshot as T1 (`eval.snapshot`), so production and eval
inputs stay identical, and run on NVWA and openFDA only (RASFF has official values).
"""

import json
from collections.abc import Mapping
from typing import Any

from openfoodalerts.classify.evidence import find_evidence, normalize
from openfoodalerts.classify.tasks import (
    ABSTAIN,
    CONFIDENCES,
    EVIDENCE_NOT_IN_INPUT,
    INVALID_OUTPUT,
    MODEL_ABSTAINED,
    Task,
    Verdict,
    abstain,
    nfc_snapshot,
)
from openfoodalerts.eval.labeling import PRODUCT_TYPES, UNKNOWN_COUNTRY
from openfoodalerts.eval.snapshot import input_snapshot
from openfoodalerts.sources.rasff.lookups import Dictionary, read_seed

SCHEMA_VERSION = "1"
SOURCES = ("nvwa", "openfda")
# T3: a Hazard is a short name ("undeclared milk", "Listeria monocytogenes"); a longer span
# is a sentence copied whole, not a Hazard.
MAX_HAZARD_CHARS = 150


def product_category_names() -> tuple[str, ...]:
    """The RASFF Product categories (seed), alphabetical as in the labelling tool."""
    return tuple(sorted(e.name for e in read_seed(Dictionary.PRODUCT_CATEGORY)))


def country_codes() -> tuple[str, ...]:
    """Two-letter RASFF country codes (ISO 3166-1 alpha-2 plus XI, XK), as in labelling."""
    return tuple(
        sorted(e.code for e in read_seed(Dictionary.COUNTRY) if e.code and len(e.code) == 2)
    )


def _span_property(description: str) -> dict[str, str]:
    return {"type": "string", "description": description}


def _schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _confidence_ok(out: Mapping[str, Any]) -> bool:
    return out.get("confidence") in CONFIDENCES


def _accepted(key: str, answer: str, confidence: str, span: str | None) -> Verdict:
    return Verdict(
        category=answer,
        confidence=confidence,
        abstained=False,
        evidence_span=span,
        abstain_reason=None,
        value={key: answer},
    )


class _Base:
    name: str
    # the key of the task's answer in ai_classifications.value
    value_key: str
    schema_version = SCHEMA_VERSION
    taxonomy_version: str | None = None
    sources: tuple[str, ...] = SOURCES
    eval_sources: tuple[str, ...] = SOURCES

    def build_input(self, source: str, row: Mapping[str, Any]) -> dict[str, str]:
        return input_snapshot(source, row)

    def render_input(self, source: str, snapshot: Mapping[str, str]) -> str:
        return json.dumps({"source": source, "input": nfc_snapshot(snapshot)}, ensure_ascii=False)

    def _abstain(self, reason: str, output: object) -> Verdict:
        return abstain(reason, output, key=self.value_key)


class _ChoiceTask(_Base):
    """One value of a fixed list, or abstain; a verbatim evidence span is required."""

    choices: tuple[str, ...]

    def output_schema(self) -> dict[str, Any]:
        return _schema(
            {
                "evidence_span": _span_property(
                    "Verbatim passage of one input field that shows the answer; empty when"
                    " abstaining."
                ),
                self.value_key: {"type": "string", "enum": [*self.choices, ABSTAIN]},
                "confidence": {"type": "string", "enum": list(CONFIDENCES)},
            }
        )

    def check(
        self, output: object, snapshot: Mapping[str, str], *, failure: str | None = None
    ) -> Verdict:
        if output is None:
            return self._abstain(failure or INVALID_OUTPUT, None)
        if not isinstance(output, Mapping):
            return self._abstain(INVALID_OUTPUT, output)
        out = dict(output)
        answer, span = out.get(self.value_key), out.get("evidence_span")
        if not isinstance(span, str) or not _confidence_ok(out):
            return self._abstain(INVALID_OUTPUT, out)
        if answer == ABSTAIN:
            return self._abstain(MODEL_ABSTAINED, out)
        if answer not in self.choices:
            return self._abstain(INVALID_OUTPUT, out)
        if find_evidence(span, snapshot) is None:
            return self._abstain(EVIDENCE_NOT_IN_INPUT, out)
        return _accepted(self.value_key, str(answer), str(out["confidence"]), span.strip())


class ProductCategoryTask(_ChoiceTask):
    """T2: the RASFF Product category of the product, or abstain."""

    name = "product_category"
    value_key = "category"

    def __init__(self) -> None:
        self.choices = product_category_names()


class ProductTypeTask(_ChoiceTask):
    """T5: food / feed / food contact material / non-food, or abstain. Internal (no badge);
    runs where the Product type rules cannot decide, before every other task (spec §4.2)."""

    name = "product_type"
    value_key = "product_type"

    def __init__(self) -> None:
        self.choices = tuple(PRODUCT_TYPES)


class HazardTask(_Base):
    """T3: the Hazard, copied verbatim from one input field, or abstain (empty hazard)."""

    name = "hazard"
    value_key = "hazard"

    def output_schema(self) -> dict[str, Any]:
        return _schema(
            {
                "hazard": _span_property(
                    "The Hazard copied character for character from one input field; empty"
                    " when the input names none."
                ),
                "confidence": {"type": "string", "enum": list(CONFIDENCES)},
            }
        )

    def check(
        self, output: object, snapshot: Mapping[str, str], *, failure: str | None = None
    ) -> Verdict:
        if output is None:
            return self._abstain(failure or INVALID_OUTPUT, None)
        if not isinstance(output, Mapping):
            return self._abstain(INVALID_OUTPUT, output)
        out = dict(output)
        hazard = out.get("hazard")
        if not isinstance(hazard, str) or not _confidence_ok(out):
            return self._abstain(INVALID_OUTPUT, out)
        span = normalize(hazard)
        if not span:
            return self._abstain(MODEL_ABSTAINED, out)
        if len(span) > MAX_HAZARD_CHARS:
            return self._abstain(INVALID_OUTPUT, out)
        if find_evidence(span, snapshot) is None:
            return self._abstain(EVIDENCE_NOT_IN_INPUT, out)
        return _accepted(self.value_key, span, str(out["confidence"]), span)


class OriginCountryTask(_Base):
    """T4: the country of origin as an ISO2 code, only when the input states it, else
    `unknown`. A country needs a verbatim span; `unknown` has none."""

    name = "origin_country"
    value_key = "country"

    def __init__(self) -> None:
        self.countries = country_codes()

    def output_schema(self) -> dict[str, Any]:
        return _schema(
            {
                "evidence_span": _span_property(
                    "Verbatim passage of one input field that states the country of origin;"
                    " empty for unknown."
                ),
                "country": {"type": "string", "enum": [UNKNOWN_COUNTRY, *self.countries]},
                "confidence": {"type": "string", "enum": list(CONFIDENCES)},
            }
        )

    def check(
        self, output: object, snapshot: Mapping[str, str], *, failure: str | None = None
    ) -> Verdict:
        if output is None:
            return self._abstain(failure or INVALID_OUTPUT, None)
        if not isinstance(output, Mapping):
            return self._abstain(INVALID_OUTPUT, output)
        out = dict(output)
        country, span = out.get("country"), out.get("evidence_span")
        if not isinstance(span, str) or not _confidence_ok(out):
            return self._abstain(INVALID_OUTPUT, out)
        confidence = str(out["confidence"])
        if country == UNKNOWN_COUNTRY:
            return _accepted(self.value_key, UNKNOWN_COUNTRY, confidence, None)
        if country not in self.countries:
            return self._abstain(INVALID_OUTPUT, out)
        if find_evidence(span, snapshot) is None:
            return self._abstain(EVIDENCE_NOT_IN_INPUT, out)
        return _accepted(self.value_key, str(country), confidence, span.strip())


# Registered in `tasks.make_task`, in spec order.
T2_T5_TASKS: dict[str, type[Task]] = {
    ProductCategoryTask.name: ProductCategoryTask,
    HazardTask.name: HazardTask,
    OriginCountryTask.name: OriginCountryTask,
    ProductTypeTask.name: ProductTypeTask,
}


def t2_t5_tasks() -> tuple[Task, ...]:
    return tuple(cls() for cls in T2_T5_TASKS.values())
