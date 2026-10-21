"""`fake`: a deterministic stand-in model for tests and local runs without an API key.

It answers every task with keyword rules, in the JSON a real model returns, so its outputs
go through exactly the same checks, storage and caching:

- T1 hazard_category: the ticket-12 keyword rules (`eval.keywords`); a match in the
  hazard-bearing fields is confidence high, elsewhere medium, no match is `abstain`;
- T2 product_category: a small table of English and Dutch product words (`_PRODUCTS`);
- T3 hazard: the text matched by the T1 keyword rules, as the Hazard;
- T4 origin_country: "Product of X" / "Made in X" / "afkomstig uit X"-style phrases with a
  country name (RASFF English names, a few Dutch ones) or a two-letter code, else unknown;
- T5 product_type: the Product type rules (`normalize.product_type`); for openFDA no hit
  means food, as the rules default;
- T6 summary_en/nl/zh: `fake_summary.summary_response` (optionally with one deliberate flaw).

The evidence span is always the matched text. It makes no network calls and reports zero
tokens. Its results are not AI classifications of any real model: do not run it on a
production database, and never cache it under a real model's name (its cache is
eval/cache/fake/, which git ignores).
"""

import re
from collections.abc import Callable, Mapping

from openfoodalerts.classify.fake_summary import summary_response
from openfoodalerts.classify.model import ModelRequest, ModelResponse
from openfoodalerts.classify.summary import SUMMARY_TASKS
from openfoodalerts.classify.tasks import ABSTAIN, HazardCategoryTask
from openfoodalerts.eval.keywords import HAZARD_FIELDS, RULES
from openfoodalerts.eval.labelset import Taxonomy
from openfoodalerts.normalize.product_type import NVWA_PATTERNS, OPENFDA_PATTERNS
from openfoodalerts.sources.rasff.lookups import Dictionary, read_seed

FAKE_MODEL = "fake"

Answer = dict[str, str]


def _first_rule(text: str) -> tuple[str, str] | None:
    """(category, matched text widened to whole words: "larv" -> "larvae")."""
    for category, pattern in RULES:
        match = pattern.search(text)
        if match:
            start, end = match.span()
            while start > 0 and text[start - 1].isalnum():
                start -= 1
            while end < len(text) and text[end].isalnum():
                end += 1
            return category, text[start:end]
    return None


def _search(pattern: re.Pattern[str], snapshot: Mapping[str, str]) -> str | None:
    """The first match in one field (spans never join fields)."""
    for value in snapshot.values():
        match = pattern.search(value)
        if match:
            return match.group(0).strip()
    return None


def _words(*words: str) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(words) + r")\b", re.IGNORECASE)


# T2: (RASFF Product category, product words), first match wins; the product lines and the
# title are searched before the rest.
_PRODUCTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("pet food", _words(r"dog", r"cat", r"pet", r"honden\w*", r"katten\w*", r"kauw\w*")),
    ("food contact materials", _words(r"\w*molens?", r"\w*pan(nen)?", r"beker\w*", r"spatel\w*")),
    (
        "dietetic foods, food supplements and fortified foods",
        _words(r"supplements?", r"capsules?", r"\w*capsules", r"protein", r"whey", r"tablets?"),
    ),
    (
        "milk and milk products",
        _words(r"cheese", r"milk", r"yogh?urt", r"\w*kaas", r"melk", r"brie", r"cream"),
    ),
    ("poultry meat and poultry meat products", _words(r"chicken", r"turkey", r"kip\w*")),
    (
        "meat and meat products (other than poultry)",
        _words(r"beef", r"pork", r"sausages?", r"\w*worst\w*", r"\w*gehakt", r"salami", r"ham"),
    ),
    (
        "fish and fish products",
        _words(r"fish", r"tuna", r"salmon", r"herring", r"vis", r"zalm", r"haring"),
    ),
    (
        "nuts, nut products and seeds",
        _words(r"\w*nuts?", r"peanuts?", r"\w*noten", r"pinda\w*", r"seeds?", r"\w*zaad"),
    ),
    (
        "herbs and spices",
        _words(
            r"spices?", r"seasoning", r"\w*kruiden\w*", r"kerrie", r"curry", r"pepper", r"cinnamon"
        ),
    ),
    ("confectionery", _words(r"candy", r"chocolate", r"snoep\w*", r"gummies", r"chocolade")),
    (
        "cereals and bakery products",
        _words(
            r"cookies?",
            r"bread",
            r"flour",
            r"\w*brood",
            r"\w*koek(en)?",
            r"bloem",
            r"pasta",
            r"rice",
        ),
    ),
    ("alcoholic beverages", _words(r"beer", r"bier", r"vodka", r"whisky")),
    ("non-alcoholic beverages", _words(r"juice", r"soda", r"drink", r"\w*sap")),
    (
        "fruits and vegetables",
        _words(
            r"fruit",
            r"vegetables?",
            r"\w*groente\w*",
            r"sprouts",
            r"onions?",
            r"peppers?",
            r"apples?",
            r"spinach",
        ),
    ),
    ("ices and desserts", _words(r"ice cream", r"pudding", r"dessert")),
)

# T4: an origin phrase followed by a country name or code.
_ORIGIN = re.compile(
    r"\b(?:product of|made in|grown in|produced in|imported from|origin:?|afkomstig uit"
    r"|herkomst:?|geproduceerd in|gemaakt in)\s+(?:the\s+)?([A-Z][A-Za-zÀ-ÿ]+(?: [A-Z][a-zÀ-ÿ]+)?)",
    re.IGNORECASE,
)
_DUTCH_COUNTRIES = {
    "nederland": "NL", "duitsland": "DE", "belgië": "BE", "frankrijk": "FR", "italië": "IT",
    "spanje": "ES", "polen": "PL", "turkije": "TR", "marokko": "MA", "griekenland": "GR",
}  # fmt: skip


def _country_names() -> dict[str, str]:
    names = {e.name.casefold(): e.code for e in read_seed(Dictionary.COUNTRY) if e.code}
    codes = {e.code.casefold(): e.code for e in read_seed(Dictionary.COUNTRY) if e.code}
    return codes | names | {"usa": "US", "u.s.a": "US"} | _DUTCH_COUNTRIES


class KeywordClassifier:
    model = FAKE_MODEL

    def __init__(
        self, taxonomy: Taxonomy, *, garble_spans: bool = False, summary_flaw: str | None = None
    ) -> None:
        self.taxonomy = taxonomy
        # quote spans that are not in the input, to exercise the substring check
        self.garble_spans = garble_spans
        self._countries = _country_names()
        # T6: break one summary check on purpose (fake_summary.FLAWS), for tests
        self.summary_flaw = summary_flaw
        self._answers: dict[str, Callable[[str, Mapping[str, str]], Answer]] = {
            HazardCategoryTask.name: self._hazard_category,
            "product_category": self._product_category,
            "hazard": self._hazard,
            "origin_country": self._origin_country,
            "product_type": self._product_type,
        }

    def complete(self, request: ModelRequest) -> ModelResponse:
        if request.task in SUMMARY_TASKS:
            return summary_response(request, self.summary_flaw)
        answer = self._answers.get(request.task)
        if answer is None:
            raise ValueError(f"the fake model does not answer {request.task}")
        return ModelResponse(answer(request.source, request.snapshot))

    def _span(self, text: str) -> str:
        return f"{text} (paraphrased)" if self.garble_spans else text

    def _hazard_hit(self, snapshot: Mapping[str, str]) -> tuple[tuple[str, str] | None, str]:
        primary = "\n".join(v for k, v in snapshot.items() if k in HAZARD_FIELDS and v)
        hit = _first_rule(primary)
        if hit is not None:
            return hit, "high"
        return _first_rule("\n".join(v for v in snapshot.values() if v)), "medium"

    def _hazard_category(self, source: str, snapshot: Mapping[str, str]) -> Answer:
        hit, confidence = self._hazard_hit(snapshot)
        label = self.taxonomy.label_for_name(hit[0]) if hit else None
        if hit is None or label is None:
            return {"evidence_span": "", "category": ABSTAIN, "confidence": "low"}
        return {"evidence_span": self._span(hit[1]), "category": label, "confidence": confidence}

    def _hazard(self, source: str, snapshot: Mapping[str, str]) -> Answer:
        hit, confidence = self._hazard_hit(snapshot)
        if hit is None:
            return {"hazard": "", "confidence": "low"}
        return {"hazard": self._span(hit[1]), "confidence": confidence}

    def _product_category(self, source: str, snapshot: Mapping[str, str]) -> Answer:
        first = {
            k: v for k, v in snapshot.items() if k in ("products", "title", "product_description")
        }
        for fields, confidence in ((first, "high"), (snapshot, "medium")):
            for category, pattern in _PRODUCTS:
                span = _search(pattern, fields)
                if span:
                    return {"evidence_span": self._span(span), "category": category,
                            "confidence": confidence}  # fmt: skip
        return {"evidence_span": "", "category": ABSTAIN, "confidence": "low"}

    def _origin_country(self, source: str, snapshot: Mapping[str, str]) -> Answer:
        for value in snapshot.values():
            for match in _ORIGIN.finditer(value):
                code = self._countries.get(match.group(1).casefold())
                if code and len(code) == 2:
                    return {"evidence_span": self._span(match.group(0)), "country": code,
                            "confidence": "high"}  # fmt: skip
        return {"evidence_span": "", "country": "unknown", "confidence": "medium"}

    def _product_type(self, source: str, snapshot: Mapping[str, str]) -> Answer:
        patterns = NVWA_PATTERNS if source == "nvwa" else OPENFDA_PATTERNS
        hits = [(kind, span) for kind, p in patterns if (span := _search(p, snapshot))]
        if hits:
            kind, span = hits[0]
            confidence = "high" if len(hits) == 1 else "medium"
            return {"evidence_span": self._span(span), "product_type": kind,
                    "confidence": confidence}  # fmt: skip
        description = snapshot.get("product_description", "").strip()
        if source == "openfda" and description:
            span = re.split(r"[;,]", description)[0].strip()
            return {"evidence_span": self._span(span), "product_type": "food",
                    "confidence": "medium"}  # fmt: skip
        return {"evidence_span": "", "product_type": ABSTAIN, "confidence": "low"}
