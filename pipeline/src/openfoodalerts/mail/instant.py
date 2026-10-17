"""`ofa send-instant` (spec §5, §10.4, §10.5): Instant emails, run after `classify`.

One Instant email per (Subscription, Notification) for every sendable Subscription with
`instant_sources`, for Notifications that

- were first seen within `LOOKBACK` before `now`, and not before the Subscription was
  confirmed. Only new Notifications: a substantial update never triggers (it goes to
  the Digest), and a Notification published more than `NEW_MAX_AGE` ago is not new
  even if just archived (backfills and replays must not send Instant emails);
- match `matches_instant` (mail/matching.py): source in `instant_sources`, the source's
  trigger rule (RASFF Alert, FDA Class I, NVWA food), and the Subscription's filters;
- were not already sent to it (sending or sent), nor already listed in one of its
  Digests (the Instant email would come after the Digest).

There is no cursor: each run looks back `LOOKBACK` and the claim's unique index skips
what was already sent, so a missed or crashed run is caught up by the next one.

At most `DAILY_CAP` Instant emails per Subscription and Amsterdam day, oldest first; the
others are only in the Digest (mail/deliveries.py `claim_instant`, which also keeps one
capped late yesterday from going out after midnight). Same claim -> send -> mark
protocol, crash behaviour and transports as the Digest.

Runs as ofa_mailer, like the Digest.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from openfoodalerts.db.connection import Connection
from openfoodalerts.jobs import JobStats, log_event, run_job
from openfoodalerts.mail import deliveries
from openfoodalerts.mail.digest import (
    NEW_MAX_AGE,
    DigestSettings,
    amsterdam_day,
    load_items,
    log_volume,
)
from openfoodalerts.mail.matching import (
    IN_SCOPE_PRODUCT_TYPES,
    NotificationFacets,
    SubscriptionFilter,
    load_facets,
    matches_instant,
)
from openfoodalerts.mail.templates import InstantEmail, render_instant
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

LOOKBACK = timedelta(hours=24)
DAILY_CAP = 5


@dataclass
class InstantRun:
    sent: int = 0
    already: int = 0
    capped: int = 0
    unsendable: int = 0
    failed: int = 0
    uncertain: int = 0
    would_send: int = 0
    # Dry run: (subscription id, notification id) of each Instant email that would go out.
    planned: list[tuple[str, int]] = field(default_factory=list)


@dataclass(frozen=True)
class _Candidate:
    first_seen_at: datetime
    facets: NotificationFacets


def _load_candidates(conn: Connection, now: datetime) -> dict[int, _Candidate]:
    rows = conn.execute(
        """
        SELECT id, first_seen_at FROM notifications
        WHERE first_seen_at >= %s AND first_seen_at < %s AND product_type = ANY(%s)
          AND (published_at IS NULL OR published_at >= %s)
        """,
        (now - LOOKBACK, now, list(IN_SCOPE_PRODUCT_TYPES), now - NEW_MAX_AGE),
    ).fetchall()
    first_seen = {r["id"]: r["first_seen_at"] for r in rows}
    facets = load_facets(conn, first_seen)
    return {nid: _Candidate(first_seen[nid], facets[nid]) for nid in first_seen}


def _chosen(
    conn: Connection, sub: Mapping[str, Any], candidates: Mapping[int, _Candidate]
) -> list[int]:
    """This Subscription's Instant emails still to send, oldest first."""
    f = SubscriptionFilter.from_row(sub)
    confirmed: datetime = sub["confirmed_at"]
    ids = sorted(
        (
            nid
            for nid, c in candidates.items()
            if c.first_seen_at >= confirmed and matches_instant(f, c.facets)
        ),
        key=lambda nid: (candidates[nid].first_seen_at, nid),
    )
    sid = str(sub["id"])
    done = deliveries.sent_instantly(conn, sid, ids) | deliveries.in_digest(conn, sid, ids)
    return [nid for nid in ids if nid not in done]


def send_instant(
    conn: Connection,
    transport: EmailTransport,
    settings: DigestSettings,
    *,
    now: datetime,
    dry_run: bool = False,
) -> InstantRun:
    """Send the Instant emails due now. Safe to re-run at any moment, also after a crash."""
    result = InstantRun()
    with run_job(conn, "send-instant", None) as stats:
        subs = [s for s in sendable_subscriptions(conn) if s["instant_sources"]]
        candidates = _load_candidates(conn, now) if subs else {}
        conn.commit()
        for sub in subs:
            chosen = _chosen(conn, sub, candidates)
            conn.commit()
            if dry_run:
                _plan(conn, sub, chosen, now, result)
                continue
            for nid in chosen:
                _send_one(conn, transport, settings, sub, nid, candidates[nid], now, result)
        log_volume(conn, amsterdam_day(now))
        _record(stats, result, transport, dry_run)
    return result


def _plan(
    conn: Connection, sub: Mapping[str, Any], chosen: list[int], now: datetime, result: InstantRun
) -> None:
    sid = str(sub["id"])
    room = max(0, DAILY_CAP - deliveries.instant_count(conn, sid, [amsterdam_day(now)]))
    conn.commit()
    result.planned.extend((sid, nid) for nid in chosen[:room])
    result.would_send += min(room, len(chosen))
    result.capped += max(0, len(chosen) - room)


def _send_one(
    conn: Connection,
    transport: EmailTransport,
    settings: DigestSettings,
    sub: Mapping[str, Any],
    nid: int,
    candidate: _Candidate,
    now: datetime,
    result: InstantRun,
) -> None:
    sid = str(sub["id"])
    locale = str(sub["locale"])
    item = load_items(conn, [nid], locale, settings.site_url)[nid]
    token = manage_token(sid, settings.token_secret)
    rendered = render_instant(
        InstantEmail(
            locale=locale,
            item=item,
            notification_type=candidate.facets.notification_type,
            manage_url=manage_url(settings.site_url, locale, token),
            unsubscribe_url=unsubscribe_url(settings.site_url, token),
            site_url=settings.site_url,
        )
    )
    # Right before sending: an unsubscribe or "delete my data" during the run counts.
    if not is_sendable(conn, sid):
        result.unsendable += 1
        conn.commit()
        return
    claim = deliveries.claim_instant(
        conn, sid, nid, now=now, first_seen_at=candidate.first_seen_at, daily_cap=DAILY_CAP
    )
    conn.commit()
    if claim == "already":
        result.already += 1
        return
    if claim == "capped":
        result.capped += 1
        return
    message = EmailMessage(
        to=str(sub["email"]),
        subject=rendered.subject,
        text=rendered.text,
        html=rendered.html,
        headers=list_unsubscribe_headers(settings.site_url, token),
        tag="instant",
    )
    try:
        sent = transport.send(message)
    except DeliveryFailed as exc:
        deliveries.mark_failed(conn, claim)
        conn.commit()
        result.failed += 1
        log_event("instant_failed", subscription_id=sid, delivery_id=claim, error=str(exc)[:300])
        return
    except DeliveryUncertain as exc:
        # Left as 'sending': this Notification is never sent to this Subscription again.
        result.uncertain += 1
        log_event("instant_uncertain", subscription_id=sid, delivery_id=claim, error=str(exc)[:300])
        return
    deliveries.mark_sent(conn, claim, sent.message_id)
    conn.commit()
    result.sent += 1


def _record(stats: JobStats, result: InstantRun, transport: EmailTransport, dry_run: bool) -> None:
    stats.extra.update(
        transport=transport.name,
        dry_run=dry_run,
        sent=result.sent,
        already=result.already,
        capped=result.capped,
        unsendable=result.unsendable,
        failed=result.failed,
        uncertain=result.uncertain,
        would_send=result.would_send,
    )
