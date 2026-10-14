"""The sampling frame: eligible Notifications as `Candidate`s, read from the database.

Eligibility (all Sources: published before `end`, so later Notifications do not change a
re-run of the sample):

- nvwa: published from 2023-10-04 (the oldest archived warning), Product type `food` as
  decided by the ticket-09 rules. Rule non-food and `pending` (mostly food contact material
  and non-food, waiting for T5) are left out; withdrawals are left out.
- openfda: published (report_date) from 2020-01-01, Product type food or feed. Products of
  one recall event share a cluster (`event_id`).
- rasff: validated from 2020-01-01, Product type food / feed / food contact material, not
  News, with at least one official Hazard. The group is the T1 label shared by all its
  Hazards, else the label of the first Hazard in source order.

The group of NVWA and FDA candidates is the keyword guess (`eval.keywords.guess_from_snapshot`:
recall reason / title + summary first, whole input as fallback) on the input snapshot,
mapped to a T1 label by the taxonomy.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any

from openfoodalerts.db.connection import Connection
from openfoodalerts.eval.keywords import guess_from_snapshot
from openfoodalerts.eval.labelset import Taxonomy
from openfoodalerts.eval.sampling import Candidate
from openfoodalerts.eval.snapshot import input_snapshot
from openfoodalerts.parse.model import SHOWN_PRODUCT_TYPES

DEFAULT_END = date(2026, 10, 25)


@dataclass(frozen=True)
class FrameConfig:
    end: date = DEFAULT_END  # exclusive, Europe/Amsterdam calendar day
    nvwa_start: date = date(2023, 10, 4)
    openfda_start: date = date(2020, 1, 1)
    rasff_start: date = date(2020, 1, 1)

    def describe(self) -> dict[str, str]:
        return {k: v.isoformat() for k, v in self.__dict__.items()}


_QUERY = """
SELECT n.id, s.code AS source, n.source_key, n.source_url, n.title, n.summary_source,
       n.product_text, n.hazard_text, n.source_fields,
       (n.published_at AT TIME ZONE 'Europe/Amsterdam')::date AS published_on,
       (SELECT array_agg(hc.rasff_id ORDER BY h.position, h.id)
          FROM notification_hazards h JOIN hazard_categories hc ON hc.id = h.hazard_category_id
         WHERE h.notification_id = n.id AND h.provenance = 'official') AS category_ids,
       (SELECT array_agg(hc.name_en ORDER BY h.position, h.id)
          FROM notification_hazards h JOIN hazard_categories hc ON hc.id = h.hazard_category_id
         WHERE h.notification_id = n.id AND h.provenance = 'official') AS category_names
FROM notifications n JOIN sources s ON s.id = n.source_id
WHERE (n.published_at AT TIME ZONE 'Europe/Amsterdam')::date < %(end)s
  AND (
    (s.code = 'nvwa' AND n.product_type = 'food'
       AND n.status_official IS DISTINCT FROM 'withdrawn'
       AND (n.published_at AT TIME ZONE 'Europe/Amsterdam')::date >= %(nvwa_start)s)
    OR (s.code = 'openfda' AND n.product_type IN ('food', 'feed')
       AND (n.published_at AT TIME ZONE 'Europe/Amsterdam')::date >= %(openfda_start)s)
    OR (s.code = 'rasff' AND n.product_type = ANY(%(shown)s) AND n.notification_type <> 'news'
       AND (n.published_at AT TIME ZONE 'Europe/Amsterdam')::date >= %(rasff_start)s)
  )
ORDER BY n.id
"""


def rasff_group(category_ids: list[int], taxonomy: Taxonomy) -> str | None:
    """The shared label, or the first Hazard's label when they differ."""
    return taxonomy.label_for_rasff_id(category_ids[0]) if category_ids else None


def _candidate(row: dict[str, Any], taxonomy: Taxonomy) -> Candidate | None:
    source = row["source"]
    snapshot = input_snapshot(source, row)
    names: tuple[str, ...] = ()
    cluster = None
    if source == "rasff":
        if not row["category_ids"]:
            return None
        group = rasff_group(row["category_ids"], taxonomy)
        names = tuple(dict.fromkeys(row["category_names"]))
    else:
        category = guess_from_snapshot(snapshot)
        group = taxonomy.label_for_name(category) if category else None
        if source == "openfda":
            cluster = row["source_fields"].get("event_id")
    return Candidate(
        source=source,
        source_key=row["source_key"],
        notification_id=row["id"],
        group=group,
        snapshot=snapshot,
        published_on=row["published_on"],
        source_url=row["source_url"],
        official_categories=names,
        cluster=cluster,
    )


def load_frame(conn: Connection, taxonomy: Taxonomy, config: FrameConfig) -> list[Candidate]:
    params = config.__dict__ | {"shown": list(SHOWN_PRODUCT_TYPES)}
    rows = conn.execute(_QUERY, params).fetchall()
    return [c for c in (_candidate(r, taxonomy) for r in rows) if c is not None]
