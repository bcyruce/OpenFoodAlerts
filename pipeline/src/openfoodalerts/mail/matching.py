"""Which Notifications a Subscription receives (spec §10.1, §10.2). Shared by the Digest
(ticket 30) and the Instant email (ticket 31).

Matching is pure Python over small value objects: the jobs load the facets of a day's
candidate Notifications once (`load_facets`, one query) and test every sendable
Subscription against them in memory. A few hundred Subscriptions times a few hundred
Notifications is well under a million cheap set operations.

Rules:
- Scope (§10.2): Product type food, feed or food contact material only. Notifications
  still waiting for T5 (product_type NULL) are out of scope until classified.
- `sources`, `hazard_categories`, `product_categories` (RASFF dictionary ids) and
  `origin_countries` (ISO2, role = origin): an empty or missing list means any.
- Official and AI values count the same (§10.1): facets are loaded regardless of
  provenance, so AI rows written later need no change here.
- `include_unclassified`: a Notification with no value at all in a filtered dimension
  (none published, or the AI abstained) matches that dimension.
- zh Subscriptions are NVWA only (§10.1); the database enforces it and so does this.
- RASFF News (`matches_news`) needs only the scope and the source; the hazard, product
  and country filters do not apply (§10.3).
- Instant email (`matches_instant`, §10.4): the source is in `instant_sources`, the
  Notification passes its source's trigger rule (`instant_trigger`), and `matches`.
  Trigger rules: RASFF classification Alert ("alert notification", the official name);
  FDA Class I; NVWA every food warning (Product type food). NVWA rows still waiting for
  T5 (product_type NULL) do not trigger: waiting is not abstaining, and they are not
  shown anywhere yet (ticket 31 log). RASFF News never triggers.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from openfoodalerts.db.connection import Connection

IN_SCOPE_PRODUCT_TYPES = frozenset({"food", "feed", "food contact material"})
RASFF_NEWS_TYPE = "news"
RASFF_ALERT_TYPE = "alert notification"
FDA_CLASS_I = "class i"


@dataclass(frozen=True)
class SubscriptionFilter:
    locale: str
    sources: frozenset[str]
    hazard_categories: frozenset[int]
    product_categories: frozenset[int]
    origin_countries: frozenset[str]
    include_unclassified: bool
    instant_sources: frozenset[str] = frozenset()

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "SubscriptionFilter":
        """From a `sendable_subscriptions` row (locale, filters, include_unclassified)."""
        filters: Mapping[str, Any] = row.get("filters") or {}
        sources = frozenset(str(s) for s in filters.get("sources") or [])
        if row["locale"] == "zh":
            sources = frozenset({"nvwa"})
        return cls(
            locale=str(row["locale"]),
            sources=sources,
            hazard_categories=frozenset(int(v) for v in filters.get("hazard_categories") or []),
            product_categories=frozenset(int(v) for v in filters.get("product_categories") or []),
            origin_countries=frozenset(str(v) for v in filters.get("origin_countries") or []),
            include_unclassified=bool(row.get("include_unclassified", True)),
            instant_sources=frozenset(str(v) for v in row.get("instant_sources") or []),
        )


@dataclass(frozen=True)
class NotificationFacets:
    """What matching looks at, official and AI values together."""

    id: int
    source: str
    product_type: str | None
    notification_type: str
    hazard_categories: frozenset[int]
    product_categories: frozenset[int]
    origin_countries: frozenset[str]
    risk_official: str | None = None

    @property
    def is_rasff_news(self) -> bool:
        return self.source == "rasff" and self.notification_type == RASFF_NEWS_TYPE


def in_scope(n: NotificationFacets) -> bool:
    return n.product_type in IN_SCOPE_PRODUCT_TYPES


def _source_ok(s: SubscriptionFilter, n: NotificationFacets) -> bool:
    return not s.sources or n.source in s.sources


def _dimension_ok[T](
    wanted: frozenset[T], values: frozenset[T], include_unclassified: bool
) -> bool:
    if not wanted:
        return True
    if not values:
        return include_unclassified
    return not wanted.isdisjoint(values)


def matches(s: SubscriptionFilter, n: NotificationFacets) -> bool:
    """Scope, source and every set filter (§10.1, §10.2). Callers decide about News."""
    return (
        in_scope(n)
        and _source_ok(s, n)
        and _dimension_ok(s.hazard_categories, n.hazard_categories, s.include_unclassified)
        and _dimension_ok(s.product_categories, n.product_categories, s.include_unclassified)
        and _dimension_ok(s.origin_countries, n.origin_countries, s.include_unclassified)
    )


def matches_news(s: SubscriptionFilter, n: NotificationFacets) -> bool:
    """RASFF News for a Subscription that includes RASFF, whatever its other filters."""
    return n.is_rasff_news and in_scope(n) and _source_ok(s, n)


def _rasff_trigger(n: NotificationFacets) -> bool:
    return n.notification_type.strip().casefold() == RASFF_ALERT_TYPE


def _fda_trigger(n: NotificationFacets) -> bool:
    return (n.risk_official or "").strip().casefold() == FDA_CLASS_I


def _nvwa_trigger(n: NotificationFacets) -> bool:
    return n.product_type == "food"


_INSTANT_TRIGGERS = {"rasff": _rasff_trigger, "openfda": _fda_trigger, "nvwa": _nvwa_trigger}


def instant_trigger(n: NotificationFacets) -> bool:
    """The source's own rule for an Instant email (spec §10.4), filters aside."""
    rule = _INSTANT_TRIGGERS.get(n.source)
    return rule is not None and not n.is_rasff_news and rule(n)


def matches_instant(s: SubscriptionFilter, n: NotificationFacets) -> bool:
    """An Instant email for this Notification: chosen source, trigger rule, filters."""
    return n.source in s.instant_sources and instant_trigger(n) and matches(s, n)


_FACETS_SQL = """
SELECT n.id, s.code AS source, n.product_type, n.notification_type, n.risk_official,
    COALESCE((SELECT array_agg(DISTINCT hc.rasff_id) FROM notification_hazards h
              JOIN hazard_categories hc ON hc.id = h.hazard_category_id
              WHERE h.notification_id = n.id), '{}') AS hazard_categories,
    COALESCE((SELECT array_agg(DISTINCT pc.rasff_id) FROM notification_product_categories p
              JOIN product_categories pc ON pc.id = p.product_category_id
              WHERE p.notification_id = n.id), '{}') AS product_categories,
    COALESCE((SELECT array_agg(DISTINCT c.country_iso2) FROM notification_countries c
              WHERE c.notification_id = n.id AND c.role = 'origin'), '{}') AS origin_countries
FROM notifications n JOIN sources s ON s.id = n.source_id
WHERE n.id = ANY(%s)
"""


def load_facets(conn: Connection, ids: Iterable[int]) -> dict[int, NotificationFacets]:
    """Facets of the given Notifications, any provenance (official and AI alike)."""
    wanted = sorted(set(ids))
    if not wanted:
        return {}
    rows = conn.execute(_FACETS_SQL, (wanted,)).fetchall()
    return {
        r["id"]: NotificationFacets(
            id=r["id"],
            source=r["source"],
            product_type=r["product_type"],
            notification_type=r["notification_type"],
            hazard_categories=frozenset(r["hazard_categories"]),
            product_categories=frozenset(r["product_categories"]),
            origin_countries=frozenset(r["origin_countries"]),
            risk_official=r["risk_official"],
        )
        for r in rows
    }
