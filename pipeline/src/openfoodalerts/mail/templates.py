"""Digest (spec §10.3) and Instant email (§10.4) content. Both show Notifications the same
way: `DigestItem` (one Notification with the §10.3 fields), `item_block` (how one is
shown), `subscription_links` (manage + unsubscribe under the separator), `footer_lines`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from openfoodalerts.mail.messages import Translator
from openfoodalerts.mail.render import (
    Block,
    EmailContent,
    Heading,
    Item,
    Link,
    Note,
    Paragraph,
    RenderedEmail,
    render_email,
)

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
SOURCE_NAMES = {"rasff": "RASFF", "nvwa": "NVWA", "openfda": "openFDA"}
# Sources that grade severity; NVWA does not (ADR 0006): shown as "not graded".
UNGRADED_SOURCES = frozenset({"nvwa"})


@dataclass(frozen=True)
class Label:
    name: str
    ai: bool


@dataclass(frozen=True)
class Summary:
    """The one-line summary: a T6 AI summary (ai=True) or source text (ai=False)."""

    text: str
    ai: bool


@dataclass(frozen=True)
class DigestItem:
    notification_id: int
    title: str
    source: str
    published_on: date | None
    severity: str | None
    hazard_categories: tuple[Label, ...]
    product_categories: tuple[Label, ...]
    summary: Summary | None
    detail_url: str
    official_url: str
    sent_instantly: bool = False
    # Updated section: Amsterdam day the substantial update was observed.
    updated_on: date | None = None

    @property
    def has_ai(self) -> bool:
        labels = (*self.hazard_categories, *self.product_categories)
        return any(label.ai for label in labels) or bool(self.summary and self.summary.ai)


@dataclass(frozen=True)
class Digest:
    locale: str
    day: date
    # Start of the window (the previous Digest, or confirmation).
    since: datetime
    new: tuple[DigestItem, ...]
    updated: tuple[DigestItem, ...]
    news: tuple[DigestItem, ...]
    manage_url: str
    unsubscribe_url: str
    site_url: str

    @property
    def items(self) -> tuple[DigestItem, ...]:
        return (*self.new, *self.updated, *self.news)

    @property
    def is_empty(self) -> bool:
        return not self.items


def _labels(t: Translator, labels: Sequence[Label]) -> str:
    return "; ".join(t("item.ai", value=label.name) if label.ai else label.name for label in labels)


def item_block(t: Translator, item: DigestItem) -> Item:
    if item.source in UNGRADED_SOURCES:
        severity: str | None = t("item.notGraded")
    else:
        severity = item.severity
    meta = [SOURCE_NAMES.get(item.source, item.source)]
    if item.published_on:
        meta.append(item.published_on.isoformat())
    if severity:
        meta.append(t("item.severity", value=severity))
    lines = [" · ".join(meta)]
    if item.updated_on:
        lines.append(t("item.updatedOn", date=item.updated_on.isoformat()))
    if item.hazard_categories:
        lines.append(t("item.hazardCategory", value=_labels(t, item.hazard_categories)))
    if item.product_categories:
        lines.append(t("item.productCategory", value=_labels(t, item.product_categories)))
    if item.summary:
        key = "item.aiSummary" if item.summary.ai else "item.sourceText"
        lines.append(t(key, text=item.summary.text))
    return Item(
        title=item.title,
        url=item.detail_url,
        badge=t("item.sentInstantly") if item.sent_instantly else None,
        lines=tuple(lines),
        links=(
            Link(t("item.details"), item.detail_url),
            Link(
                t("item.official", source=SOURCE_NAMES.get(item.source, item.source)),
                item.official_url,
            ),
        ),
    )


def subscription_links(t: Translator, manage_url: str, unsubscribe_url: str) -> tuple[Link, ...]:
    return (Link(t("links.manage"), manage_url), Link(t("links.unsubscribe"), unsubscribe_url))


def footer_lines(t: Translator, site_url: str, reason_key: str) -> tuple[str, ...]:
    return (t("footer"), t(reason_key, site=urlsplit(site_url).netloc or site_url))


def render_digest(digest: Digest) -> RenderedEmail:
    t = Translator(digest.locale)
    since = digest.since.astimezone(AMSTERDAM).strftime("%Y-%m-%d %H:%M")
    blocks: list[Block] = [Paragraph(t("digest.intro", since=since))]
    for key, items in (
        ("digest.new", digest.new),
        ("digest.updated", digest.updated),
        ("digest.news", digest.news),
    ):
        if not items:
            continue
        blocks.append(Heading(t(key, count=len(items))))
        if key == "digest.news":
            blocks.append(Note(t("digest.newsIntro")))
        blocks.extend(item_block(t, item) for item in items)
    if any(item.has_ai for item in digest.items):
        blocks.append(Note(t("item.aiNote")))
    return render_email(
        EmailContent(
            locale=digest.locale,
            subject=t("digest.subject", date=digest.day.isoformat()),
            blocks=tuple(blocks),
            footer_links=subscription_links(t, digest.manage_url, digest.unsubscribe_url),
            footer=footer_lines(t, digest.site_url, "digest.reason"),
        )
    )


# Room for "openFDA, Class I: " and a mail client's preview; the body has the full title.
SUBJECT_TITLE_CHARS = 110


@dataclass(frozen=True)
class InstantEmail:
    """One Notification sent right away (spec §10.4)."""

    locale: str
    item: DigestItem
    # The Notification's official notification_type (RASFF: its classification name).
    notification_type: str
    manage_url: str
    unsubscribe_url: str
    site_url: str


def official_classification(t: Translator, item: DigestItem, notification_type: str) -> str:
    """What the source calls it, untranslated like the severity: the RASFF classification
    ("alert notification"), FDA's class ("Class I"); NVWA warnings are not graded."""
    if item.source == "nvwa":
        return t("instant.nvwaWarning")
    if item.source == "openfda" and item.severity:
        return item.severity
    return notification_type


def _shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip(" ,;:-") + "…"


def render_instant(email: InstantEmail) -> RenderedEmail:
    t = Translator(email.locale)
    item = email.item
    source = SOURCE_NAMES.get(item.source, item.source)
    classification = official_classification(t, item, email.notification_type)
    blocks: list[Block] = [
        Paragraph(t("instant.intro", source=source, classification=classification)),
        item_block(t, item),
        Note(t("instant.digestNote")),
    ]
    if item.has_ai:
        blocks.append(Note(t("item.aiNote")))
    return render_email(
        EmailContent(
            locale=email.locale,
            subject=t(
                "instant.subject",
                source=source,
                classification=classification,
                title=_shorten(" ".join(item.title.split()), SUBJECT_TITLE_CHARS),
            ),
            blocks=tuple(blocks),
            footer_links=subscription_links(t, email.manage_url, email.unsubscribe_url),
            footer=footer_lines(t, email.site_url, "instant.reason"),
        )
    )
