"""The labelling tool's logic (eval/label_app.py is only the Streamlit UI around it).

- Annotator A labels every item; annotator B only the agreement subset (spec §7.1).
- Progress lives in labels.csv: the next item is the first one, in items.csv order (dev
  first), without a row by this annotator under this guideline version. Stopping at any
  point and restarting resumes there.
- Blind second annotation: a session only ever reads its own annotator's rows.
- Validation (one message per wrong field):
  T1 hazard_category: a T1 label or "unsure";
  T2 product_category: a RASFF Product category or "unsure";
  T3 hazard: a verbatim substring of one input field, or "none" (no Hazard named);
  T4 origin_country: an ISO 3166-1 alpha-2 code from the RASFF country list, or "unknown"
     (only when the text states the origin, spec §6.1);
  T5 product_type: food / feed / food contact material / non-food.
  An item labelled non-food is later excluded and replaced (`ofa eval-exclude --from-labels`).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from openfoodalerts.eval.files import TASKS, ItemRow, append_label, read_labels
from openfoodalerts.parse.model import ProductType
from openfoodalerts.sources.rasff.lookups import Dictionary, read_seed

UNSURE = "unsure"
NO_HAZARD = "none"
UNKNOWN_COUNTRY = "unknown"
PRODUCT_TYPES: tuple[ProductType, ...] = ("food", "feed", "food contact material", "non-food")


@dataclass(frozen=True)
class Options:
    hazard_categories: tuple[str, ...]
    product_categories: tuple[str, ...]
    countries: tuple[str, ...]
    product_types: tuple[str, ...] = PRODUCT_TYPES


def default_options(labels: Sequence[str]) -> Options:
    """Choices for each task: the T1 labels given, RASFF Product categories and countries."""
    products = sorted(e.name for e in read_seed(Dictionary.PRODUCT_CATEGORY))
    countries = sorted(e.code for e in read_seed(Dictionary.COUNTRY) if e.code and len(e.code) == 2)
    return Options(
        hazard_categories=(*labels, UNSURE),
        product_categories=(*products, UNSURE),
        countries=(UNKNOWN_COUNTRY, *countries),
    )


def normalize(values: Mapping[str, str]) -> dict[str, str]:
    out = {task: (values.get(task) or "").strip() for task in TASKS}
    if out["origin_country"] != UNKNOWN_COUNTRY:
        out["origin_country"] = out["origin_country"].upper()
    return out


def validate(item: ItemRow, values: Mapping[str, str], options: Options) -> list[str]:
    v = normalize(values)
    errors = []
    if v["hazard_category"] not in options.hazard_categories:
        errors.append("hazard_category: choose a T1 label or 'unsure'")
    if v["product_category"] not in options.product_categories:
        errors.append("product_category: choose a RASFF Product category or 'unsure'")
    span = v["hazard"]
    if not span:
        errors.append(f"hazard: copy the Hazard from the text, or write '{NO_HAZARD}'")
    elif span != NO_HAZARD and not any(span in text for text in item.input.values()):
        errors.append("hazard: must be copied verbatim from one field of the text")
    if v["origin_country"] not in options.countries:
        errors.append("origin_country: an ISO2 code such as NL, or 'unknown'")
    if v["product_type"] not in options.product_types:
        errors.append("product_type: food, feed, food contact material or non-food")
    return errors


class LabelSession:
    """One annotator labelling under one guideline version."""

    def __init__(
        self, items: Sequence[ItemRow], labels_path: Path, annotator: str, guideline_version: str
    ) -> None:
        if annotator not in ("A", "B"):
            raise ValueError("annotator must be A or B")
        self.labels_path = labels_path
        self.annotator = annotator
        self.guideline_version = guideline_version
        self.items = [i for i in items if annotator == "A" or i.agreement]

    def _own_rows(self) -> list[dict[str, str]]:
        return [
            r
            for r in read_labels(self.labels_path)
            if r["annotator"] == self.annotator and r["guideline_version"] == self.guideline_version
        ]

    def _done(self) -> set[str]:
        return {r["item_id"] for r in self._own_rows()}

    def next_item(self) -> ItemRow | None:
        done = self._done()
        return next((i for i in self.items if i.item_id not in done), None)

    def progress(self) -> tuple[int, int]:
        ids = {i.item_id for i in self.items}
        return len(self._done() & ids), len(ids)

    def own_label(self, item_id: str) -> dict[str, str] | None:
        """This annotator's latest values for an item (never another annotator's)."""
        rows = [r for r in self._own_rows() if r["item_id"] == item_id]
        return {task: rows[-1][task] for task in TASKS} if rows else None

    def save(self, item: ItemRow, values: Mapping[str, str], *, note: str, now: datetime) -> None:
        append_label(
            self.labels_path,
            {
                "item_id": item.item_id,
                "annotator": self.annotator,
                "guideline_version": self.guideline_version,
                **normalize(values),
                "note": note.strip(),
                "labelled_at": now.isoformat(timespec="seconds"),
            },
        )
