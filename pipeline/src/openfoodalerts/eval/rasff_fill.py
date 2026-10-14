"""`ofa eval-fetch-rasff`: fetch the RASFF Notifications the eval sample needs, before the
full backfill (ticket 08) exists.

The RASFF part of the eval set (60 items) is sampled from the local frame like the other
Sources. Until the backfill has run, the local frame only holds recent Notifications, so
the rare labels cannot be filled. This job:

1. estimates the RASFF demand per label: the sampler is run on the real NVWA/FDA frame
   plus a stand-in RASFF frame with as many candidates per label as the taxonomy CSV counts
   since 2020 (so RASFF's proportional share follows its real distribution);
2. plans, per label, the demand plus a margin minus the local RASFF candidates;
3. per planned label, lists Notifications with the list endpoint filtered by the label's
   Hazard categories, the frame dates and Product type food/feed/FCM (page 1, plus one
   seeded random page when there are several), and fetches the details of the lowest
   ranked ones that are not archived yet. List pages and details are archived exactly as
   in `backfill-rasff`, through the same rate-limited client (>= 3 s between requests).

Afterwards run `ofa parse --source rasff` and `ofa eval-sample`. After the backfill the
local frame is complete and this job plans nothing.
"""

import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from openfoodalerts.db.connection import Connection
from openfoodalerts.eval.labelset import Taxonomy
from openfoodalerts.eval.sampling import (
    Candidate,
    SamplingConfig,
    build_eval_set,
    deduplicate,
    rank,
)
from openfoodalerts.jobs import log_event, run_job
from openfoodalerts.sources.rasff.backfill import (
    RasffFetchError,
    archived_detail_keys,
    fetch_detail,
    fetch_list_page,
)
from openfoodalerts.sources.rasff.client import RasffClient
from openfoodalerts.taxonomy import SHOWN_PRODUCT_TYPES

PAGE_SIZE = 99  # the backend rejects 100 and more
DEFAULT_MARGIN = 0.25


def rasff_demand(
    frame: Iterable[Candidate], taxonomy: Taxonomy, config: SamplingConfig
) -> Counter[str]:
    """RASFF items per label the sampler would take from a complete RASFF frame."""
    stand_in = [c for c in frame if c.source != "rasff"]
    for label in taxonomy.labels:
        for i in range(taxonomy.counts.get(label, 0)):
            key = f"stand-in:{label}:{i}"
            stand_in.append(Candidate("rasff", key, 0, label, {}, None, ""))
    result = build_eval_set(stand_in, taxonomy.labels, config)
    return Counter(
        i.candidate.group for i in result.items if i.source == "rasff" and i.candidate.group
    )


def fetch_plan(
    frame: Iterable[Candidate], demand: Mapping[str, int], *, margin: float, seed: int
) -> dict[str, int]:
    """Label -> RASFF Notifications to fetch (demand plus margin, minus the local ones)."""
    local = Counter(c.group for c in deduplicate(frame, seed) if c.source == "rasff")
    plan = {}
    for label, wanted in demand.items():
        missing = math.ceil(wanted * (1 + margin)) - local[label]
        if missing > 0:
            plan[label] = missing
    return plan


def estimate_requests(plan: Mapping[str, int]) -> int:
    """At most two list pages per label plus one request per detail."""
    return sum(2 + n for n in plan.values())


def _list_date(day: date) -> str:
    return day.strftime("%d-%m-%Y 00:00:00")


@dataclass
class FillResult:
    fetched: dict[str, int] = field(default_factory=dict)
    available: dict[str, int] = field(default_factory=dict)


def fill_rasff(
    conn: Connection,
    client: RasffClient,
    plan: Mapping[str, int],
    taxonomy: Taxonomy,
    *,
    seed: int,
    since: date,
    until: date,
) -> FillResult:
    """Fetch and archive the planned details (module docstring, step 3)."""
    out = FillResult()
    with run_job(conn, "eval-fetch-rasff", None, client.http) as stats:
        archived = archived_detail_keys(conn)
        for label, wanted in plan.items():
            listed = _list_label(
                conn, client, taxonomy.category_ids(label), seed, label, since, until
            )
            out.available[label] = len(listed)
            fresh = [item for item in listed if str(item["reference"]) not in archived]
            fresh.sort(key=lambda item: rank(seed, "rasff", str(item["reference"])))
            out.fetched[label] = 0
            for item in fresh:
                if out.fetched[label] >= wanted:
                    break
                reference = str(item["reference"])
                try:
                    ok = fetch_detail(conn, client, int(item["notifId"]), reference, stats)
                except RasffFetchError as exc:
                    # some old details answer 500 for good; take the next candidate
                    log_event("rasff_detail_failed", reference=reference, error=str(exc))
                    stats.errors.append(str(exc))
                    continue
                if ok:
                    archived.add(reference)
                    out.fetched[label] += 1
        stats.extra.update(fetched=out.fetched, listed=out.available)
    return out


def _list_label(
    conn: Connection,
    client: RasffClient,
    category_ids: Sequence[int],
    seed: int,
    label: str,
    since: date,
    until: date,
) -> list[dict[str, Any]]:
    filters = {
        "ecValidDateFrom": _list_date(since),
        "ecValidDateTo": _list_date(until),
        "hazardCategory": list(category_ids),
        "notificationType": list(SHOWN_PRODUCT_TYPES),
    }
    first = fetch_list_page(conn, client, 1, PAGE_SIZE, filters)
    items: list[dict[str, Any]] = list(first.get("notifications") or [])
    pages = int(first.get("totalPages") or 1)
    if pages > 1:
        page = 1 + int(rank(seed, "rasff-page", label), 16) % pages
        if page != 1:
            items = list(
                fetch_list_page(conn, client, page, PAGE_SIZE, filters).get("notifications") or []
            )
    return items
