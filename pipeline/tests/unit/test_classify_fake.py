"""The fake model answers every task with keyword rules, through the same task checks."""

import pytest

from openfoodalerts.classify.fake import KeywordClassifier
from openfoodalerts.classify.model import ModelRequest
from openfoodalerts.classify.prompts import load_prompt
from openfoodalerts.classify.run import classify
from openfoodalerts.classify.tasks import make_task
from openfoodalerts.eval.labelset import default_taxonomy_path, load_taxonomy

TAXONOMY = load_taxonomy(default_taxonomy_path())
FAKE = KeywordClassifier(TAXONOMY)


def answer(task_name: str, source: str, **snapshot: str) -> tuple[str | None, str | None]:
    task = make_task(task_name, TAXONOMY)
    result = classify(task, load_prompt(task_name), FAKE, source, snapshot)
    return result.verdict.category, result.verdict.confidence


def nvwa(title: str, summary: str = "", products: str = "") -> dict[str, str]:
    return {"title": title, "summary": summary, "products": products}


def fda(description: str, reason: str = "") -> dict[str, str]:
    return {"product_description": description, "reason_for_recall": reason}


@pytest.mark.parametrize(
    ("snapshot", "expected"),
    [
        (nvwa("Veiligheidswaarschuwing pepermolen", "Er komt lood vrij."), "food contact material"),
        (nvwa("Veiligheidswaarschuwing kauwbotjes voor honden"), "feed"),
        (nvwa("Veiligheidswaarschuwing speelgoed", "Gebruik het speelgoed niet."), "non-food"),
        (nvwa("Veiligheidswaarschuwing kaas", "Bevat Listeria. Eet de kaas niet."), "food"),
        (nvwa("Veiligheidswaarschuwing Zeeman"), None),
    ],
)
def test_t5_product_type(snapshot: dict[str, str], expected: str | None) -> None:
    assert answer("product_type", "nvwa", **snapshot)[0] == expected


def test_t2_t3_t4() -> None:
    cheese = nvwa("Veiligheidswaarschuwing Peperkaas", "Hierin is mogelijk Listeria aanwezig.")
    assert answer("product_category", "nvwa", **cheese) == ("milk and milk products", "high")
    assert answer("hazard", "nvwa", **cheese) == ("Listeria", "high")
    assert answer("origin_country", "nvwa", **cheese) == ("unknown", "medium")
    pecorino = fda("Pecorino cheese wheels. Product of Italy.", "Potential Listeria contamination")
    assert answer("origin_country", "openfda", **pecorino) == ("IT", "high")
    assert answer("origin_country", "openfda", **fda("Peppers; Product of MX"))[0] == "MX"
    assert answer("product_category", "openfda", **fda("Widget 3000")) == (None, None)
    assert answer("hazard", "openfda", **fda("Widget 3000", "Recalled")) == (None, None)


def test_t3_spans_are_whole_words() -> None:
    larvae = fda("Flour 5 lb", "Product may contain larvae.")
    assert answer("hazard", "openfda", **larvae)[0] == "larvae"


def test_garbled_spans_fail_the_check_for_every_task() -> None:
    garbling = KeywordClassifier(TAXONOMY, garble_spans=True)
    snapshot = nvwa("Waarschuwing kaas", "Bevat Listeria. Eet de kaas niet.")
    for name in ("product_category", "hazard", "product_type"):
        task = make_task(name, TAXONOMY)
        result = classify(task, load_prompt(name), garbling, "nvwa", snapshot)
        assert result.verdict.abstain_reason == "evidence_not_in_input", name
    with pytest.raises(ValueError, match="does not answer"):
        garbling.complete(ModelRequest("summary", "nvwa", snapshot, system="", user=""))


def test_t5_on_fda() -> None:
    assert answer("product_type", "openfda", **fda("DOG TREATS 8 oz"))[0] == "feed"
    assert answer("product_type", "openfda", **fda("Cookies 12 oz", "Undeclared milk"))[0] == "food"
