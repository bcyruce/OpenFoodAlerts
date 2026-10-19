"""`fake`: a deterministic stand-in model for tests and local runs without an API key.

It answers T1 with the ticket-12 keyword rules (`eval.keywords`), in the JSON a real model
returns, so its outputs go through exactly the same checks, storage and caching:
a match in the hazard-bearing fields is confidence high, elsewhere medium, no match is
`abstain`; the evidence span is the matched text. It makes no network calls and reports
zero tokens. Its results are not AI classifications of any real model: do not run it on a
production database, and never cache it under a real model's name (its cache is
eval/cache/fake/, which git ignores).
"""

from openfoodalerts.classify.model import ModelRequest, ModelResponse
from openfoodalerts.classify.tasks import ABSTAIN, HazardCategoryTask
from openfoodalerts.eval.keywords import HAZARD_FIELDS, RULES
from openfoodalerts.eval.labelset import Taxonomy

FAKE_MODEL = "fake"


def _first_rule(text: str) -> tuple[str, str] | None:
    for category, pattern in RULES:
        match = pattern.search(text)
        if match:
            return category, match.group(0)
    return None


class KeywordClassifier:
    model = FAKE_MODEL

    def __init__(self, taxonomy: Taxonomy, *, garble_spans: bool = False) -> None:
        self.taxonomy = taxonomy
        # quote spans that are not in the input, to exercise the substring check
        self.garble_spans = garble_spans

    def complete(self, request: ModelRequest) -> ModelResponse:
        if request.task != HazardCategoryTask.name:
            raise ValueError(f"the fake model only answers {HazardCategoryTask.name}")
        snapshot = request.snapshot
        primary = "\n".join(v for k, v in snapshot.items() if k in HAZARD_FIELDS and v)
        hit, confidence = _first_rule(primary), "high"
        if hit is None:
            hit, confidence = _first_rule("\n".join(v for v in snapshot.values() if v)), "medium"
        label = self.taxonomy.label_for_name(hit[0]) if hit else None
        if hit is None or label is None:
            return ModelResponse({"evidence_span": "", "category": ABSTAIN, "confidence": "low"})
        span = f"{hit[1]} (paraphrased)" if self.garble_spans else hit[1]
        return ModelResponse({"evidence_span": span, "category": label, "confidence": confidence})
