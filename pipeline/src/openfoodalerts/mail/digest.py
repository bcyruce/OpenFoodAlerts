"""`ofa send-digest` (spec §5, §10.3, §10.5): the daily Digest, 07:00 Europe/Amsterdam.

For every sendable Subscription the window runs from the previous sent Digest (or the
confirmation, for the first one) to `now`, at most `MAX_WINDOW` back:

- New: Notifications first seen in the window that match the filters (mail/matching.py).
  Ones already sent by Instant email are listed and marked. A Notification published
  more than `NEW_MAX_AGE` before `now` is not new, even if we only just archived it
  (backfills and parser replays must not flood Digests).
- Updated: Notifications, not new, with a substantial version (`is_substantial`)
  observed in the window, that match the filters.
- RASFF News: new RASFF News, if the Subscription includes RASFF; the hazard, product
  and country filters do not apply.

Nothing in any section: no email. At most one Digest per Subscription per Amsterdam day,
and a re-run after a crash never sends twice (mail/deliveries.py). The window reaches
`OVERLAP` further back than the previous Digest so that rows committed late by a
concurrent parse are not missed; Notifications already in an earlier Digest are dropped.

Runs as ofa_mailer: it reads only `sendable_subscriptions`, public tables and
email_deliveries, and writes email_deliveries.
"""

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from openfoodalerts.db.connection import Connection
from openfoodalerts.jobs import JobStats, log_event, run_job
from openfoodalerts.mail import deliveries
from openfoodalerts.mail.matching import (
    IN_SCOPE_PRODUCT_TYPES,
    NotificationFacets,
    SubscriptionFilter,
    load_facets,
    matches,
    matches_news,
)
from openfoodalerts.mail.paths import notification_path
from openfoodalerts.mail.summaries import ai_summaries, summary_line
from openfoodalerts.mail.templates import AMSTERDAM, Digest, DigestItem, Label, render_digest
from openfoodalerts.mail.transport import (
    DeliveryFailed,
    DeliveryUncertain,
    EmailMessage,
    EmailTransport,
)
from openfoodalerts.subscriptions.links import (
    list_unsubscribe_headers,
    manage_token,
    manage_url,
    unsubscribe_url,
)
from openfoodalerts.subscriptions.sendable import is_sendable, sendable_subscriptions

MAX_WINDOW = timedelta(days=7)
OVERLAP = timedelta(hours=1)
NEW_MAX_AGE = timedelta(days=30)
# Brevo's free tier sends 300 emails a day (spec §10.5); warn from this many.
BREVO_DAILY_LIMIT = 300
VOLUME_WARNING = 250
# Detail pages exist in en and nl only (spec §9); zh Digests link to the English page.
DETAIL_LOCALES = {"en": "en", "nl": "nl", "zh": "en"}
DEFAULT_SITE_URL = "https://openfoodalerts.nl"
# The website's fallback when OFA_TOKEN_SECRET is unset outside production
# (web/lib/subscriptions/runtime.ts), so local manage links work on both sides.
DEV_TOKEN_SECRET = "development-only-not-secret"


@dataclass(frozen=True)
class DigestSettings:
    site_url: str
    token_secret: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "DigestSettings":
        """SITE_URL and OFA_TOKEN_SECRET; the secret is required when sending for real."""
        env = os.environ if env is None else env
        secret = env.get("OFA_TOKEN_SECRET")
        if not secret:
            if env.get("EMAIL_TRANSPORT") == "brevo":
                raise ValueError("OFA_TOKEN_SECRET is not set (needed for EMAIL_TRANSPORT=brevo)")
            secret = DEV_TOKEN_SECRET
        return cls(site_url=env.get("SITE_URL") or DEFAULT_SITE_URL, token_secret=secret)


@dataclass
class DigestRun:
    day: date
    sent: int = 0
    empty: int = 0
    already: int = 0
    unsendable: int = 0
    failed: int = 0
    uncertain: int = 0
    would_send: int = 0
    # Dry run: (subscription id, new, updated, news) per Digest that would go out.
    planned: list[tuple[str, int, int, int]] = field(default_factory=list)


@dataclass(frozen=True)
class _Candidates:
    first_seen: dict[int, datetime]
    # (notification id, observed_at) of substantial versions after the first.
    updates: list[tuple[int, datetime]]
    facets: dict[int, NotificationFacets]


def amsterdam_day(moment: datetime) -> date:
    return moment.astimezone(AMSTERDAM).date()


def _load_candidates(conn: Connection, since: datetime, until: datetime) -> _Candidates:
    scope = list(IN_SCOPE_PRODUCT_TYPES)
    new_rows = conn.execute(
        """
        SELECT id, first_seen_at FROM notifications
        WHERE first_seen_at >= %s AND first_seen_at < %s AND product_type = ANY(%s)
          AND (published_at IS NULL OR published_at >= %s)
        """,
        (since, until, scope, until - NEW_MAX_AGE),
    ).fetchall()
    update_rows = conn.execute(
        """
        SELECT v.notification_id, v.observed_at FROM notification_versions v
        JOIN notifications n ON n.id = v.notification_id
        WHERE v.is_substantial AND v.version > 1 AND v.observed_at >= %s AND v.observed_at < %s
          AND n.product_type = ANY(%s)
        """,
        (since, until, scope),
    ).fetchall()
    first_seen = {r["id"]: r["first_seen_at"] for r in new_rows}
    updates = [(r["notification_id"], r["observed_at"]) for r in update_rows]
    facets = load_facets(conn, [*first_seen, *(nid for nid, _ in updates)])
    return _Candidates(first_seen=first_seen, updates=updates, facets=facets)


def _previously_digested(conn: Connection, subscription_id: str, since: datetime) -> set[int]:
    rows = conn.execute(
        """
        SELECT DISTINCT unnest(notification_ids) AS id FROM email_deliveries
        WHERE subscription_id = %s AND kind = 'digest' AND status = 'sent' AND sent_at >= %s
        """,
        (subscription_id, since),
    ).fetchall()
    return {r["id"] for r in rows}


@dataclass(frozen=True)
class _Selection:
    new: list[int]
    updated: dict[int, datetime]
    news: list[int]

    @property
    def ids(self) -> list[int]:
        return [*self.new, *self.updated, *self.news]


def _select(
    conn: Connection,
    sub: Mapping[str, Any],
    start: datetime,
    candidates: _Candidates,
) -> _Selection:
    """What one Subscription's Digest lists, as Notification ids per section."""
    f = SubscriptionFilter.from_row(sub)
    reach = start - OVERLAP
    seen_before = _previously_digested(conn, str(sub["id"]), reach - MAX_WINDOW)
    new: list[int] = []
    news: list[int] = []
    for nid, first_seen in candidates.first_seen.items():
        n = candidates.facets[nid]
        if first_seen < reach or nid in seen_before:
            continue
        if n.is_rasff_news:
            if matches_news(f, n):
                news.append(nid)
        elif matches(f, n):
            new.append(nid)
    listed = set(new) | set(news)
    updated: dict[int, datetime] = {}
    for nid, observed in candidates.updates:
        n = candidates.facets[nid]
        if observed < reach or nid in listed or n.is_rasff_news or not matches(f, n):
            continue
        # Inside the overlap, an update already covered by the previous Digest is skipped.
        if observed < start and nid in seen_before:
            continue
        updated[nid] = max(observed, updated.get(nid, observed))
    return _Selection(new=new, updated=updated, news=news)


_DISPLAY_SQL = """
SELECT n.id, s.code AS source, n.source_key, n.source_url, n.title, n.published_at,
    n.risk_official, n.hazard_text, n.summary_source
FROM notifications n JOIN sources s ON s.id = n.source_id
WHERE n.id = ANY(%s)
"""

# A category listed both officially and by the AI shows as official.
_LABELS_SQL = """
SELECT x.notification_id, c.name_en, c.name_nl, c.name_zh, bool_and(x.provenance = 'ai') AS ai
FROM {table} x JOIN {categories} c ON c.id = x.{column}
WHERE x.notification_id = ANY(%s)
GROUP BY x.notification_id, c.id
ORDER BY x.notification_id, c.name_en
"""


def _labels(
    conn: Connection, table: str, categories: str, column: str, ids: list[int], locale: str
) -> dict[int, tuple[Label, ...]]:
    rows = conn.execute(
        _LABELS_SQL.format(table=table, categories=categories, column=column), (ids,)
    ).fetchall()
    out: dict[int, list[Label]] = {}
    for r in rows:
        name = r.get(f"name_{locale}") or r["name_en"]
        out.setdefault(r["notification_id"], []).append(Label(name, ai=bool(r["ai"])))
    return {k: tuple(v) for k, v in out.items()}


def load_items(
    conn: Connection,
    ids: Sequence[int],
    locale: str,
    site_url: str,
    *,
    instant: set[int] | None = None,
    updated: Mapping[int, datetime] | None = None,
) -> dict[int, DigestItem]:
    """The §10.3 fields of these Notifications in a Subscription's language (Digest and
    Instant email alike)."""
    instant = instant or set()
    updated = updated or {}
    wanted = list(ids)
    rows = conn.execute(_DISPLAY_SQL, (wanted,)).fetchall()
    hazards = _labels(
        conn, "notification_hazards", "hazard_categories", "hazard_category_id", wanted, locale
    )
    products = _labels(
        conn,
        "notification_product_categories",
        "product_categories",
        "product_category_id",
        wanted,
        locale,
    )
    ai = ai_summaries(conn, wanted, locale)
    base = site_url.rstrip("/")
    detail_locale = DETAIL_LOCALES[locale]
    items: dict[int, DigestItem] = {}
    for r in rows:
        nid = r["id"]
        observed = updated.get(nid)
        items[nid] = DigestItem(
            notification_id=nid,
            title=r["title"],
            source=r["source"],
            published_on=amsterdam_day(r["published_at"]) if r["published_at"] else None,
            severity=r["risk_official"],
            hazard_categories=hazards.get(nid, ()),
            product_categories=products.get(nid, ()),
            summary=summary_line(
                r["source"],
                ai_text=ai.get(nid),
                summary_source=r["summary_source"],
                hazard_text=r["hazard_text"],
            ),
            detail_url=base + notification_path(detail_locale, r["source"], r["source_key"]),
            official_url=r["source_url"],
            sent_instantly=nid in instant,
            updated_on=amsterdam_day(observed) if observed else None,
        )
    return items


def _ordered(items: Mapping[int, DigestItem], ids: Sequence[int]) -> tuple[DigestItem, ...]:
    """Newest publication first; undated last; then by id."""
    chosen = [items[i] for i in ids if i in items]
    chosen.sort(
        key=lambda it: (
            it.published_on is None,
            -(it.published_on.toordinal() if it.published_on else 0),
            it.notification_id,
        )
    )
    return tuple(chosen)


def _window_start(conn: Connection, sub: Mapping[str, Any], now: datetime) -> datetime:
    previous = deliveries.last_sent_digest_at(conn, str(sub["id"]))
    start: datetime = previous or sub["confirmed_at"]
    return max(start, now - MAX_WINDOW)


def send_digest(
    conn: Connection,
    transport: EmailTransport,
    settings: DigestSettings,
    *,
    now: datetime,
    dry_run: bool = False,
) -> DigestRun:
    """Send the day's Digests. Safe to re-run at any moment, also after a crash."""
    day = amsterdam_day(now)
    result = DigestRun(day=day)
    with run_job(conn, "send-digest", None) as stats:
        subs = []
        for s in sendable_subscriptions(conn):
            if deliveries.digest_claimed(conn, str(s["id"]), day):
                result.already += 1
            else:
                subs.append(s)
        starts = {str(s["id"]): _window_start(conn, s, now) for s in subs}
        earliest = min(starts.values(), default=now) - OVERLAP
        candidates = _load_candidates(conn, earliest, now)
        conn.commit()
        for sub in subs:
            _digest_one(
                conn,
                transport,
                settings,
                sub,
                starts[str(sub["id"])],
                now,
                candidates,
                result,
                dry_run=dry_run,
            )
        log_volume(conn, day)
        _record(stats, result, transport, dry_run)
    return result


def _digest_one(
    conn: Connection,
    transport: EmailTransport,
    settings: DigestSettings,
    sub: Mapping[str, Any],
    start: datetime,
    now: datetime,
    candidates: _Candidates,
    result: DigestRun,
    *,
    dry_run: bool,
) -> None:
    sid = str(sub["id"])
    locale = str(sub["locale"])
    selection = _select(conn, sub, start, candidates)
    if not selection.ids:
        result.empty += 1
        return
    instant = deliveries.sent_instantly(conn, sid, selection.new)
    items = load_items(
        conn, selection.ids, locale, settings.site_url, instant=instant, updated=selection.updated
    )
    token = manage_token(sid, settings.token_secret)
    digest = Digest(
        locale=locale,
        day=result.day,
        since=start,
        new=_ordered(items, selection.new),
        updated=_ordered(items, list(selection.updated)),
        news=_ordered(items, selection.news),
        manage_url=manage_url(settings.site_url, locale, token),
        unsubscribe_url=unsubscribe_url(settings.site_url, token),
        site_url=settings.site_url,
    )
    rendered = render_digest(digest)
    conn.commit()
    if dry_run:
        result.would_send += 1
        result.planned.append((sid, len(digest.new), len(digest.updated), len(digest.news)))
        return
    # Right before sending: an unsubscribe or "delete my data" during the run counts.
    if not is_sendable(conn, sid):
        result.unsendable += 1
        conn.commit()
        return
    claim = deliveries.claim_digest(conn, sid, now, [i.notification_id for i in digest.items])
    conn.commit()
    if claim is None:
        result.already += 1
        return
    message = EmailMessage(
        to=str(sub["email"]),
        subject=rendered.subject,
        text=rendered.text,
        html=rendered.html,
        headers=list_unsubscribe_headers(settings.site_url, token),
        tag="digest",
    )
    try:
        sent = transport.send(message)
    except DeliveryFailed as exc:
        deliveries.mark_failed(conn, claim)
        conn.commit()
        result.failed += 1
        log_event("digest_failed", subscription_id=sid, delivery_id=claim, error=str(exc)[:300])
        return
    except DeliveryUncertain as exc:
        # Left as 'sending': the day is used up, nothing is sent twice.
        result.uncertain += 1
        log_event("digest_uncertain", subscription_id=sid, delivery_id=claim, error=str(exc)[:300])
        return
    deliveries.mark_sent(conn, claim, sent.message_id)
    conn.commit()
    result.sent += 1


def log_volume(conn: Connection, day: date) -> None:
    """The day's Brevo volume (spec §10.5); every mailer job logs it after its run."""
    by_kind = deliveries.daily_volume(conn, day)
    total = sum(by_kind.values())
    log_event(
        "send_volume", day=day.isoformat(), total=total, by_kind=by_kind, limit=BREVO_DAILY_LIMIT
    )
    if total >= VOLUME_WARNING:
        log_event(
            "send_volume_high",
            day=day.isoformat(),
            total=total,
            limit=BREVO_DAILY_LIMIT,
            message="near the Brevo free tier; consider the paid plan (spec §10.5)",
        )


def _record(stats: JobStats, result: DigestRun, transport: EmailTransport, dry_run: bool) -> None:
    stats.extra.update(
        day=result.day.isoformat(),
        transport=transport.name,
        dry_run=dry_run,
        sent=result.sent,
        empty=result.empty,
        already=result.already,
        unsendable=result.unsendable,
        failed=result.failed,
        uncertain=result.uncertain,
        would_send=result.would_send,
    )
