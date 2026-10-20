"""T6 summary (spec §6.1): a neutral summary of at most 40 words that only restates the
source, per language: NVWA in en, nl and zh, openFDA in en and nl, never RASFF.
"""

import json
import math
import re
import unicodedata
from collections.abc import Mapping
from typing import Any

from openfoodalerts.classify.tasks import (
    CONFIDENCES,
    INVALID_OUTPUT,
    MODEL_ABSTAINED,
    Verdict,
    nfc_snapshot,
)
from openfoodalerts.eval.snapshot import input_snapshot

MAX_WORDS = 40
# Languages and the Sources summarized in each (spec §6.1); RASFF never.
LOCALE_SOURCES: dict[str, tuple[str, ...]] = {
    "en": ("nvwa", "openfda"),
    "nl": ("nvwa", "openfda"),
    "zh": ("nvwa",),
}
LOCALES = tuple(LOCALE_SOURCES)


def summary_task_name(locale: str) -> str:
    """The task name of the summary in one language: one task per language, so the
    language is part of every ai_classifications key and the newest row per
    (notification_id, task) stays the current one."""
    return f"summary_{locale}"


SUMMARY_TASKS = tuple(summary_task_name(locale) for locale in LOCALES)

# Why a summary is an abstain (value.abstain_reason), besides those of `tasks`:
TOO_LONG = "too_long"  # more than MAX_WORDS words (`word_count`)
NUMBER_NOT_IN_INPUT = "number_not_in_input"  # a number the source does not have
CONTAINS_LINK = "contains_link"  # a URL, domain or e-mail address (the email has the links)
WRONG_LANGUAGE = "wrong_language"  # not in the task's language (heuristic)
TRADITIONAL_CHINESE = "traditional_chinese"  # zh must be Simplified Chinese

# Function words that occur in only one of the two languages ("in", "is", "of" occur in
# both and are left out). Product names rarely contain them.
_EN_WORDS = (
    "the and with for to from this that by be been has have was were are not it its may"
    " because due which contains could"
)
_NL_WORDS = (
    "de het een en met voor naar dit deze die door bij zijn wordt worden niet kan kunnen"
    " omdat ook op te uit aan om er vanwege bevat"
)
_EN, _NL = frozenset(_EN_WORDS.split()), frozenset(_NL_WORDS.split())
# Frequent Traditional characters whose Simplified form differs (food-safety vocabulary).
_TRADITIONAL_ONLY = frozenset(
    "們這為產過檢醫藥類發開關會國應對與無營養雞麵魚蝦貝點則請標籤識號碼購買銷說報製誤黴"
    "汙殘農屬鐵鉛鎘運輸進廠區當時間來後見現實體質準處劑腸桿險風嚴豬蘭衛該種個經單鹽塊裝"
    "環黃麴"
)
SEVERITY_NOT_IN_INPUT = "severity_not_in_input"  # grades or judges severity (ADR 0006)

# Severity grades and judgements, one pattern per meaning in en, nl and zh. A summary may
# use one only when the source has the same meaning in any of the languages (a Chinese
# summary of a Dutch warning that says "gevaarlijk" may say 危险).
_SEVERITY = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        # recall class / grade
        r"\b(?:class|klasse)\s+(?:i{1,3}|[123])\b|[一二三]级|I{1,3}级",
        # serious, severe
        r"\b(?:serious(?:ly)?|severe(?:ly)?|ernstig\w*)\b|严重",
        # dangerous
        r"\b(?:danger\w*|hazardous|gevaar\w*)\b|危险",
        # life-threatening, fatal
        r"\b(?:life[- ]threatening|fatal|deadly|lethal|death|levensgevaarlijk\w*|dodelijk\w*"
        r"|overlijden|overleden)\b|致命|危及生命|死亡",
        # a risk level
        r"\b(?:high|low|major|minor)[- ]risk\b|\b(?:hoog|laag|groot|klein)\s+risico\b"
        r"|[高低]风险|重大风险",
    )
)

_DIGITS = re.compile(r"[0-9]+")
# a URL, "www." or an e-mail address; and a bare domain name, which is allowed only when
# the source has it (a brand such as "Nuts.com")
_LINK = re.compile(r"https?://|\bwww\.|[\w.+-]+@[\w-]+\.\w", re.IGNORECASE)
_DOMAIN = re.compile(r"\b[\w-]+\.(?:nl|com|org|net|gov|eu|be|de|fr|uk|us|info|io)\b", re.IGNORECASE)

# CJK Unified Ideographs (+ extension A and compatibility ideographs)
_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
# a run of letters or digits that is not Chinese (a Latin word, a number, "350g")
_LATIN_TOKEN = re.compile(r"[^\W_㐀-䶿一-鿿豈-﫿]+")


def word_count(text: str, locale: str) -> int:
    """Length in words. en/nl: whitespace-separated tokens with a letter or digit. zh: two
    Chinese characters count as one word (rounded up), plus every Latin word or number
    (brand and product names stay in Dutch)."""
    if locale == "zh":
        return math.ceil(len(_CJK.findall(text)) / 2) + len(_LATIN_TOKEN.findall(text))
    return sum(1 for token in text.split() if any(c.isalnum() for c in token))


def summary_problem(text: str, locale: str, snapshot: Mapping[str, str]) -> str | None:
    """Why a (whitespace-collapsed) summary cannot be used, or None."""
    if not text:
        return INVALID_OUTPUT
    if word_count(text, locale) > MAX_WORDS:
        return TOO_LONG
    source = "\n".join(snapshot.values())
    domains = (m.group(0).casefold() for m in _DOMAIN.finditer(text))
    if _LINK.search(text) or any(d not in source.casefold() for d in domains):
        return CONTAINS_LINK
    language = _language_problem(text, locale)
    if language is not None:
        return language
    if any(p.search(text) and not p.search(source) for p in _SEVERITY):
        return SEVERITY_NOT_IN_INPUT
    if not _numbers(text) <= _numbers(*snapshot.values()):
        return NUMBER_NOT_IN_INPUT
    return None


def _language_problem(text: str, locale: str) -> str | None:
    """Cheap language checks. zh: Chinese sentences (at least as many Chinese characters
    as Latin words, which allows Dutch brand names) in Simplified characters. en/nl: no
    Chinese, and not more function words of the other language than of its own."""
    cjk = _CJK.findall(text)
    if locale == "zh":
        if len(cjk) < max(1, len(_LATIN_TOKEN.findall(text))):
            return WRONG_LANGUAGE
        if any(c in _TRADITIONAL_ONLY for c in cjk):
            return TRADITIONAL_CHINESE
        return None
    if cjk:
        return WRONG_LANGUAGE
    words = re.findall(r"[^\W\d_]+", text.casefold())
    own, other = (_EN, _NL) if locale == "en" else (_NL, _EN)
    if sum(w in other for w in words) > sum(w in own for w in words):
        return WRONG_LANGUAGE
    return None


def _numbers(*texts: str) -> set[int]:
    """The digit runs of the texts as numbers: "07-01-2027" -> {7, 1, 2027}, so a summary
    may reorder a date or drop leading zeros, but not add a number. Full-width digits
    (zh) count as digits (NFKC)."""
    return {
        int(run) for text in texts for run in _DIGITS.findall(unicodedata.normalize("NFKC", text))
    }


def _abstain(locale: str, reason: str, output: object) -> Verdict:
    return Verdict(
        category=None,
        confidence=None,
        abstained=True,
        evidence_span=None,
        abstain_reason=reason,
        value={"locale": locale, "summary": None, "abstain_reason": reason, "model_output": output},
    )


class SummaryTask:
    """T6 in one language: one task (and one row per Notification) per language."""

    schema_version = "1"
    taxonomy_version: str | None = None

    def __init__(self, locale: str) -> None:
        if locale not in LOCALE_SOURCES:
            raise ValueError(f"no T6 summary in {locale!r}; languages: {', '.join(LOCALES)}")
        self.locale = locale
        self.name = summary_task_name(locale)
        self.sources = LOCALE_SOURCES[locale]
        # scored by the human fact-check of eval items of the same Sources (spec §7.2)
        self.eval_sources = self.sources

    def build_input(self, source: str, row: Mapping[str, Any]) -> dict[str, str]:
        return input_snapshot(source, row)

    def render_input(self, source: str, snapshot: Mapping[str, str]) -> str:
        return json.dumps({"source": source, "input": nfc_snapshot(snapshot)}, ensure_ascii=False)

    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "abstain": {"type": "boolean"},
                "summary": {"type": "string"},
                "confidence": {"type": "string", "enum": list(CONFIDENCES)},
            },
            "required": ["abstain", "summary", "confidence"],
            "additionalProperties": False,
        }

    def check(
        self, output: object, snapshot: Mapping[str, str], *, failure: str | None = None
    ) -> Verdict:
        if not isinstance(output, Mapping):
            return _abstain(self.locale, failure or INVALID_OUTPUT, output)
        out = dict(output)
        # A reviewer's correction (classify.review.check_correction) comes without
        # `abstain` (and with an evidence_span, which T6 ignores): a summary is not one.
        flag = out.get("abstain", False)
        summary, confidence = out.get("summary"), out.get("confidence")
        if (
            not isinstance(flag, bool)
            or not isinstance(summary, str)
            or confidence not in CONFIDENCES
        ):
            return _abstain(self.locale, INVALID_OUTPUT, out)
        if flag:
            return _abstain(self.locale, MODEL_ABSTAINED, out)
        text = " ".join(summary.split())
        reason = summary_problem(text, self.locale, snapshot)
        if reason is not None:
            return _abstain(self.locale, reason, out)
        return Verdict(
            category=text,
            confidence=str(confidence),
            abstained=False,
            evidence_span=None,
            abstain_reason=None,
            value={"locale": self.locale, "summary": text},
        )


def summary_tasks() -> tuple[SummaryTask, ...]:
    """T6 in every language (en, nl, zh)."""
    return tuple(SummaryTask(locale) for locale in LOCALES)
