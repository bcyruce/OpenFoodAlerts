"""The T1 label set, read from a taxonomy CSV (spec §6.2, ADR 0003).

The CSV has one row per RASFF Hazard category: `rasff_id, name_en, <count>, label`. The
frozen file is `db/seed/taxonomy/v1.csv` (ticket 11); until it exists the draft
`v1-draft.csv` is used, so everything built on the label set can be re-run unchanged after
the freeze.
"""

import csv
from dataclasses import dataclass
from pathlib import Path

from openfoodalerts.sources.rasff.lookups import normalize_name

OTHER = "other"
FROZEN_FILE = "v1.csv"
DRAFT_FILE = "v1-draft.csv"


def default_taxonomy_dir() -> Path:
    # labelset.py -> eval -> openfoodalerts -> src -> pipeline -> repo root
    return Path(__file__).resolve().parents[4] / "db" / "seed" / "taxonomy"


def default_taxonomy_path(directory: Path | None = None) -> Path:
    """The frozen taxonomy if it exists, else the draft."""
    directory = directory or default_taxonomy_dir()
    frozen = directory / FROZEN_FILE
    return frozen if frozen.exists() else directory / DRAFT_FILE


@dataclass(frozen=True)
class Taxonomy:
    version: str
    # distinct labels in file order (most frequent first), "other" last
    labels: tuple[str, ...]
    _by_name: dict[str, str]
    _by_rasff_id: dict[int, str]
    # label -> RASFF Notifications counted for its categories (the CSV's count column)
    counts: dict[str, int]

    def category_ids(self, label: str) -> tuple[int, ...]:
        return tuple(i for i, lab in self._by_rasff_id.items() if lab == label)

    def label_for_name(self, category_name: str) -> str | None:
        """T1 label of a RASFF Hazard category name (case and spacing ignored)."""
        return self._by_name.get(normalize_name(category_name))

    def label_for_rasff_id(self, rasff_id: int) -> str | None:
        return self._by_rasff_id.get(rasff_id)


def _version(path: Path) -> str:
    """ "v1.csv" -> "1" (spec: taxonomy_version = 1); a draft keeps its stem."""
    stem = path.stem
    if stem.startswith("v") and stem[1:].isdigit():
        return stem[1:]
    return stem


def load_taxonomy(path: Path) -> Taxonomy:
    by_name: dict[str, str] = {}
    by_id: dict[int, str] = {}
    labels: list[str] = []
    counts: dict[str, int] = {}
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        for values in reader:
            row = dict(zip(header, values, strict=True))
            label = row["label"].strip()
            if not label:
                raise ValueError(f"{path.name}: category {row['rasff_id']} has no label")
            by_name[normalize_name(row["name_en"])] = label
            by_id[int(row["rasff_id"])] = label
            # third column: notifications_since_<date>
            counts[label] = counts.get(label, 0) + int(values[2] or 0)
            if label not in labels:
                labels.append(label)
    ordered = [label for label in labels if label != OTHER]
    if OTHER in labels:
        ordered.append(OTHER)
    return Taxonomy(_version(path), tuple(ordered), by_name, by_id, counts)
