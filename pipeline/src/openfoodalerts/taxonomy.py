"""Draft of the T1 label set (spec §6.2, ADR 0003; ticket 11).

Counts RASFF Notifications per Hazard category since a date with the list endpoint's
`hazardCategory` filter (its `totalElements`), so the draft needs no full backfill. A
Notification with Hazards in several categories counts once in each. The draft merges
"GMO / novel food", "genetically modified" and "novel food", then folds categories with
fewer than 30 Notifications into "other". The domain expert reviews it before it is frozen
as taxonomy v1.
"""

import csv
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from openfoodalerts.sources.rasff.client import RasffClient
from openfoodalerts.sources.rasff.lookups import Dictionary, lookup

THRESHOLD = 30
OTHER = "other"
GMO_LABEL = "GMO / novel food"
GMO_GROUP = frozenset({"GMO / novel food", "genetically modified", "novel food"})
# RASFF product types shown on the site: food, feed, food contact material (spec §4.2).
SHOWN_PRODUCT_TYPES = (283, 282, 281)


@dataclass(frozen=True)
class CategoryCount:
    rasff_id: int
    name: str
    count: int
    label: str = ""


def count_hazard_categories(
    client: RasffClient, *, since: str, product_types: Sequence[int] = SHOWN_PRODUCT_TYPES
) -> list[CategoryCount]:
    """`since` uses the list filter format, e.g. "01-01-2020 00:00:00"."""
    counts = []
    for entry in lookup(Dictionary.HAZARD_CATEGORY):
        filters = {
            "ecValidDateFrom": since,
            "hazardCategory": [entry.id],
            "notificationType": list(product_types),
        }
        response = client.search(1, items_per_page=1, filters=filters)
        response.raise_for_status()
        counts.append(CategoryCount(entry.id, entry.name, int(response.json()["totalElements"])))
    return counts


def draft_merge(counts: Sequence[CategoryCount], threshold: int = THRESHOLD) -> list[CategoryCount]:
    """Assign each category its draft T1 label."""
    gmo_total = sum(c.count for c in counts if c.name in GMO_GROUP)
    rows = []
    for c in counts:
        total = gmo_total if c.name in GMO_GROUP else c.count
        name = GMO_LABEL if c.name in GMO_GROUP else c.name
        rows.append(replace(c, label=name if total >= threshold else OTHER))
    return rows


def write_draft(rows: Sequence[CategoryCount], path: Path, since: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["rasff_id", "name_en", f"notifications_since_{since[:10]}", "label"])
        for r in sorted(rows, key=lambda r: (-r.count, r.name)):
            writer.writerow([r.rasff_id, r.name, r.count, r.label])
