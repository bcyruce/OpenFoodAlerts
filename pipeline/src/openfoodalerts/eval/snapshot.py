"""The frozen model input of an eval item (`eval_items.input_snapshot`).

Fields are copied verbatim from the parsed Notification, in the source language, so the
model sees what the annotator saw even if the Source later edits the record:

- rasff: `subject` (the Notification title) only (spec §6.1: RASFF T1 sees only `subject`);
- nvwa: `title`, `summary` (the `.intro` paragraph, `summary_source`), `products` (the
  product lines, `product_text`);
- openfda: `product_description` and `reason_for_recall`. The recalling firm and its
  city/state/country are left out: they say where the firm is, not where the product comes
  from, and would bias T4 (origin only when the text states it).

Field order is part of the format: classifiers build their prompt from the fields in this
order, and T3 spans must be verbatim substrings of one field.
"""

from collections.abc import Mapping
from typing import Any

# Source -> (snapshot field, notifications column)
FIELDS: dict[str, tuple[tuple[str, str], ...]] = {
    "rasff": (("subject", "title"),),
    "nvwa": (("title", "title"), ("summary", "summary_source"), ("products", "product_text")),
    "openfda": (("product_description", "product_text"), ("reason_for_recall", "hazard_text")),
}


def input_snapshot(source: str, row: Mapping[str, Any]) -> dict[str, str]:
    return {field: str(row.get(column) or "") for field, column in FIELDS[source]}


def snapshot_text(snapshot: Mapping[str, str]) -> str:
    """The non-empty fields joined by newlines (keyword rules, display)."""
    return "\n".join(value for value in snapshot.values() if value)
