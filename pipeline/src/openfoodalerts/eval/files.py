"""The committed eval CSVs (format documented in eval/README.md).

All files are UTF-8 without BOM, LF line endings, comma-separated with minimal quoting and
a fixed column order. Nothing time-dependent is written, so re-running the sampler on the
same frame gives byte-identical files.
"""

import _csv
import csv
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from openfoodalerts.eval.sampling import EvalItem

ITEM_COLUMNS = (
    "item_id",
    "split",
    "source",
    "source_key",
    "source_url",
    "published_on",
    "stratum",
    "noise_audit",
    "agreement",
    "official_categories",
    "input",
)
# One row per (item, annotator) labelling pass; a later row for the same item and annotator
# supersedes an earlier one. Task columns use the spec §6.1 task names.
TASKS = ("hazard_category", "product_category", "hazard", "origin_country", "product_type")
LABEL_COLUMNS = (
    "item_id",
    "annotator",
    "guideline_version",
    *TASKS,
    "note",
    "labelled_at",
)
EXCLUSION_COLUMNS = ("item_id", "reason", "replaced_by")
CATEGORY_SEPARATOR = "; "


@dataclass(frozen=True)
class ItemRow:
    item_id: str
    split: str
    source: str
    source_key: str
    source_url: str
    published_on: str
    stratum: str
    noise_audit: bool
    agreement: bool
    official_categories: tuple[str, ...]
    input: dict[str, str]


@dataclass(frozen=True)
class Exclusion:
    item_id: str
    reason: str
    replaced_by: str | None = None


def _flag(value: bool) -> str:
    return "true" if value else "false"


def _writer(f: TextIO) -> "_csv.Writer":
    return csv.writer(f, lineterminator="\n")


def write_items(path: Path, items: Iterable[EvalItem]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = _writer(f)
        writer.writerow(ITEM_COLUMNS)
        for i in items:
            c = i.candidate
            writer.writerow(
                [
                    i.item_id,
                    i.split,
                    c.source,
                    c.source_key,
                    c.source_url,
                    c.published_on.isoformat() if c.published_on else "",
                    c.stratum,
                    _flag(i.noise_audit),
                    _flag(i.agreement),
                    CATEGORY_SEPARATOR.join(c.official_categories),
                    json.dumps(dict(c.snapshot), ensure_ascii=False),
                ]
            )


def read_items(path: Path) -> list[ItemRow]:
    with path.open(encoding="utf-8", newline="") as f:
        return [
            ItemRow(
                item_id=r["item_id"],
                split=r["split"],
                source=r["source"],
                source_key=r["source_key"],
                source_url=r["source_url"],
                published_on=r["published_on"],
                stratum=r["stratum"],
                noise_audit=r["noise_audit"] == "true",
                agreement=r["agreement"] == "true",
                official_categories=tuple(
                    c for c in r["official_categories"].split(CATEGORY_SEPARATOR) if c
                ),
                input=json.loads(r["input"]),
            )
            for r in csv.DictReader(f)
        ]


def ensure_labels_file(path: Path) -> None:
    """Create the Label CSV with its header if it does not exist yet."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        _writer(f).writerow(LABEL_COLUMNS)


def read_labels(path: Path) -> list[dict[str, str]]:
    """Label rows in file order (empty when the file does not exist)."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def append_label(path: Path, row: Mapping[str, str]) -> None:
    ensure_labels_file(path)
    with path.open("a", encoding="utf-8", newline="") as f:
        _writer(f).writerow([row.get(column, "") for column in LABEL_COLUMNS])


def read_exclusions(path: Path) -> list[Exclusion]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return [
            Exclusion(r["item_id"], r["reason"], r["replaced_by"] or None)
            for r in csv.DictReader(f)
        ]


def write_exclusions(path: Path, rows: Sequence[Exclusion]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = _writer(f)
        writer.writerow(EXCLUSION_COLUMNS)
        for r in rows:
            writer.writerow([r.item_id, r.reason, r.replaced_by or ""])
