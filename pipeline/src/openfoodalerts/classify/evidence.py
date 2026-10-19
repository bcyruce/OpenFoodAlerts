"""The `evidence_span` check (spec §6.3, ADR 0006): the span must be in the model input.

A span counts as found when, after the normalization below, it is a substring of one
input field (a span joining two fields is not found, as for T3 Hazards). Normalization,
applied to the span and the fields alike:

1. Unicode NFC (the form the model input is sent in, see `input_hash`);
2. every run of whitespace (spaces, tabs, newlines) becomes one space;
3. leading and trailing whitespace is removed.

Nothing else: case, punctuation, spelling and language must match, so the span is the
source's own words. A span shorter than MIN_CHARS after normalization is not evidence
("a" would be found in almost any text). Failing the check means abstain.
"""

import re
import unicodedata
from collections.abc import Mapping

MIN_CHARS = 3
_SPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    return _SPACE.sub(" ", unicodedata.normalize("NFC", text)).strip()


def find_evidence(span: str | None, snapshot: Mapping[str, str]) -> str | None:
    """The input field that contains the span, or None if the span is not evidence."""
    needle = normalize(span or "")
    if len(needle) < MIN_CHARS:
        return None
    for field, value in snapshot.items():
        if needle in normalize(value):
            return field
    return None
