"""The fake model's T6 answers (see `classify.fake`): a fixed sentence per language that
names the product with the source's own first words, so it restates nothing wrong and
passes every check; `flaw` makes it break one check on purpose, for tests.

It is obviously not a summary (it says "fake"): never show it to readers.
"""

from collections.abc import Mapping

from openfoodalerts.classify.model import ModelRequest, ModelResponse

FLAWS = ("too_long", "new_number", "link", "wrong_language", "severity", "not_json")
_NAME_WORDS = 5
_SOURCE_NAMES = {"nvwa": "NVWA", "openfda": "FDA"}
_TEMPLATES = {
    "en": "Fake summary for testing: the {source} notice about {product} is restated here"
    " without new facts.",
    "nl": "Nepsamenvatting (fake) voor tests: de melding van de {source} over {product} wordt hier"
    " zonder nieuwe feiten herhaald.",
    "zh": "测试用假模型摘要：此处复述{source}关于 {product} 的通报，不添加新的事实。",
}
_SEVERITY = {"en": " This is a serious risk.", "nl": " Dit is ernstig.", "zh": "风险严重。"}


def _product(snapshot: Mapping[str, str]) -> str:
    text = snapshot.get("title") or snapshot.get("product_description") or ""
    words = [w for w in text.split() if w.casefold() != "veiligheidswaarschuwing"]
    return " ".join(words[:_NAME_WORDS])


def summary_response(request: ModelRequest, flaw: str | None = None) -> ModelResponse:
    locale = request.task.removeprefix("summary_")
    product = _product(request.snapshot)
    if not product:
        return ModelResponse({"abstain": True, "summary": "", "confidence": "low"})
    if flaw == "not_json":
        return ModelResponse(f"Summary: {product}")
    written = "en" if flaw == "wrong_language" and locale == "zh" else locale
    if flaw == "wrong_language" and locale != "zh":
        written = "zh" if locale == "en" else "en"
    source = _SOURCE_NAMES.get(request.source, request.source)
    summary = _TEMPLATES[written].format(source=source, product=product)
    if flaw == "too_long":
        summary = " ".join([summary] * 4)
    elif flaw == "new_number":
        summary += " 1234567"
    elif flaw == "link":
        summary += " https://example.org/recall"
    elif flaw == "severity":
        summary += _SEVERITY[locale]
    return ModelResponse({"abstain": False, "summary": summary, "confidence": "medium"})
