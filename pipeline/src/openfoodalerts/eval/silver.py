"""RASFF silver set (spec §7.1): `ofa eval-silver`.

From the RASFF Notifications validated since 2020 (Product type food / feed / food contact
material, no News), keep those whose official Hazards all map to one T1 label: their label
is unambiguous, so it can stand in for a human Label when a model sees only the `subject`.
"Same category" is judged after the taxonomy merge (novel food + genetically modified is one
label); the share with several raw RASFF categories is reported too. Notifications in the
hand-labelled eval set are left out, so the silver set can train the TF-IDF baseline
(ticket 15) without leaking eval items.

Stratified by label: proportional to the eligible counts, with a floor of
min(available, 25) per label, lowest seeded ranks first (the eval sampler's allocation).
"""

import csv
from collections import defaultdict
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from openfoodalerts.db.connection import Connection
from openfoodalerts.eval.frame import FrameConfig
from openfoodalerts.eval.labelset import Taxonomy
from openfoodalerts.eval.sampling import allocate, rank
from openfoodalerts.parse.model import SHOWN_PRODUCT_TYPES

DEFAULT_SIZE = 2000
LABEL_FLOOR = 25
SILVER_COLUMNS = ("source_key", "published_on", "label", "rasff_categories", "subject")


@dataclass(frozen=True)
class RasffRecord:
    source_key: str
    published_on: date | None
    subject: str
    category_ids: tuple[int, ...]
    category_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class SilverRow:
    source_key: str
    published_on: date | None
    label: str
    rasff_categories: tuple[str, ...]
    subject: str


@dataclass(frozen=True)
class SilverStats:
    notifications: int
    no_hazards: int
    with_hazards: int
    # Hazards in more than one T1 label: excluded from the silver set
    multi_label: int
    # Hazards in more than one raw RASFF category (before the taxonomy merge)
    multi_category: int
    eligible: int

    @property
    def excluded_share(self) -> float:
        return self.multi_label / self.with_hazards if self.with_hazards else 0.0

    @property
    def multi_category_share(self) -> float:
        return self.multi_category / self.with_hazards if self.with_hazards else 0.0


@dataclass(frozen=True)
class Silver:
    rows: list[SilverRow]
    stats: SilverStats
    available: dict[str, int]


def build_silver(
    records: Iterable[RasffRecord],
    taxonomy: Taxonomy,
    *,
    size: int,
    seed: int,
    exclude: Collection[str] = (),
) -> Silver:
    pool: dict[str, list[tuple[str, SilverRow]]] = defaultdict(list)
    counts = {"notifications": 0, "no_hazards": 0, "multi_label": 0, "multi_category": 0}
    for r in records:
        counts["notifications"] += 1
        if not r.category_ids:
            counts["no_hazards"] += 1
            continue
        if len(set(r.category_ids)) > 1:
            counts["multi_category"] += 1
        labels = {taxonomy.label_for_rasff_id(i) for i in r.category_ids}
        if len(labels) > 1 or None in labels:
            counts["multi_label"] += 1
            continue
        if r.source_key in exclude:
            continue
        [label] = labels
        assert label is not None
        names = tuple(dict.fromkeys(r.category_names)) or tuple(
            str(i) for i in dict.fromkeys(r.category_ids)
        )
        row = SilverRow(r.source_key, r.published_on, label, names, r.subject)
        pool[label].append((rank(seed, "silver", r.source_key), row))
    with_hazards = counts["notifications"] - counts["no_hazards"]
    available = {label: len(rows) for label, rows in pool.items()}
    allocation, _ = allocate(
        {("rasff", label): n for label, n in available.items()},
        {"rasff": size},
        [label for label in taxonomy.labels if label in available],
        LABEL_FLOOR,
        {"rasff": 1.0},
    )
    chosen = []
    for (_, label), n in allocation.items():
        assert label is not None
        chosen += sorted(pool[label], key=lambda rr: rr[0])[:n]
    stats = SilverStats(
        notifications=counts["notifications"],
        no_hazards=counts["no_hazards"],
        with_hazards=with_hazards,
        multi_label=counts["multi_label"],
        multi_category=counts["multi_category"],
        eligible=sum(available.values()),
    )
    return Silver([row for _, row in sorted(chosen, key=lambda rr: rr[0])], stats, available)


def write_silver(path: Path, rows: Sequence[SilverRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(SILVER_COLUMNS)
        for r in rows:
            writer.writerow(
                [
                    r.source_key,
                    r.published_on.isoformat() if r.published_on else "",
                    r.label,
                    "; ".join(r.rasff_categories),
                    r.subject,
                ]
            )


_QUERY = """
SELECT n.source_key, n.title,
       (n.published_at AT TIME ZONE 'Europe/Amsterdam')::date AS published_on,
       coalesce((SELECT array_agg(hc.rasff_id ORDER BY h.position, h.id)
          FROM notification_hazards h JOIN hazard_categories hc ON hc.id = h.hazard_category_id
         WHERE h.notification_id = n.id AND h.provenance = 'official'), '{}') AS category_ids,
       coalesce((SELECT array_agg(hc.name_en ORDER BY h.position, h.id)
          FROM notification_hazards h JOIN hazard_categories hc ON hc.id = h.hazard_category_id
         WHERE h.notification_id = n.id AND h.provenance = 'official'), '{}') AS category_names
FROM notifications n JOIN sources s ON s.id = n.source_id
WHERE s.code = 'rasff' AND n.product_type = ANY(%(shown)s) AND n.notification_type <> 'news'
  AND (n.published_at AT TIME ZONE 'Europe/Amsterdam')::date >= %(start)s
  AND (n.published_at AT TIME ZONE 'Europe/Amsterdam')::date < %(end)s
ORDER BY n.id
"""


def load_rasff_records(
    conn: Connection, frame: FrameConfig, *, start: date | None = None
) -> list[RasffRecord]:
    rows = conn.execute(
        _QUERY,
        {"shown": list(SHOWN_PRODUCT_TYPES), "start": start or frame.rasff_start, "end": frame.end},
    ).fetchall()
    return [
        RasffRecord(
            r["source_key"],
            r["published_on"],
            r["title"],
            tuple(r["category_ids"]),
            tuple(r["category_names"]),
        )
        for r in rows
    ]
