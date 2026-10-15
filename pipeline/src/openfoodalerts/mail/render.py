"""Email template framework (spec §10.5), the Python twin of web/lib/email/render.ts.

A template lists content blocks once and gets a plain-text and an HTML version that say
the same thing. HTML is escaped here, so templates pass plain strings. Inline styles,
the same colours and fonts as the website's confirmation email; no images, tracking
pixels or promotional content.

Blocks beyond the web's (paragraph, note): `Heading` for a section and `Item` for one
Notification (linked title, a badge, detail lines, links). Ticket 31 (Instant email)
builds its content from the same blocks.
"""

from dataclasses import dataclass, field
from html import escape

HTML_LANG = {"en": "en", "nl": "nl", "zh": "zh-Hans"}

TEXT_COLOR = "#0f172a"
MUTED_COLOR = "#475569"
LINK_COLOR = "#1d4ed8"


@dataclass(frozen=True)
class Link:
    label: str
    url: str


@dataclass(frozen=True)
class Paragraph:
    text: str


@dataclass(frozen=True)
class Note:
    text: str


@dataclass(frozen=True)
class Heading:
    text: str


@dataclass(frozen=True)
class Item:
    title: str
    url: str
    lines: tuple[str, ...] = ()
    links: tuple[Link, ...] = ()
    badge: str | None = None


Block = Paragraph | Note | Heading | Item


@dataclass(frozen=True)
class EmailContent:
    locale: str
    subject: str
    blocks: tuple[Block, ...]
    # Manage and unsubscribe links, shown under the separator (spec §10.5).
    footer_links: tuple[Link, ...] = ()
    # Short lines under the separator: who sends the email and why.
    footer: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    text: str
    html: str


def _e(value: str) -> str:
    return escape(value, quote=True)


def _block_text(block: Block) -> str:
    match block:
        case Paragraph(text) | Note(text):
            return text
        case Heading(text):
            return f"{text}\n{'=' * len(text)}"
        case Item(title, _url, lines, links, badge):
            # The title's link is one of `links` (the detail page), so plain text skips it.
            head = f"* {title}" + (f" [{badge}]" if badge else "")
            rest = [*lines, *(f"{link.label}: {link.url}" for link in links)]
            return "\n".join([head, *(f"  {line}" for line in rest)])


def _block_html(block: Block) -> str:
    match block:
        case Paragraph(text):
            return f'<p style="margin:0 0 16px">{_e(text)}</p>'
        case Note(text):
            return f'<p style="margin:0 0 16px;font-size:14px;color:{MUTED_COLOR}">{_e(text)}</p>'
        case Heading(text):
            return f'<h2 style="margin:32px 0 12px;font-size:20px;line-height:1.3">{_e(text)}</h2>'
        case Item(title, url, lines, links, badge):
            badge_html = (
                f' <span style="font-size:13px;font-weight:400;color:{MUTED_COLOR};'
                f'border:1px solid #cbd5e1;border-radius:4px;padding:0 6px">{_e(badge)}</span>'
                if badge
                else ""
            )
            lines_html = "".join(
                f'<p style="margin:0 0 2px;font-size:14px;color:{MUTED_COLOR}">{_e(line)}</p>'
                for line in lines
            )
            links_html = " · ".join(
                f'<a href="{_e(link.url)}" style="color:{LINK_COLOR}">{_e(link.label)}</a>'
                for link in links
            )
            return (
                '<div style="margin:0 0 20px">'
                f'<p style="margin:0 0 4px;font-weight:600"><a href="{_e(url)}" '
                f'style="color:{TEXT_COLOR}">{_e(title)}</a>{badge_html}</p>'
                f"{lines_html}"
                + (f'<p style="margin:4px 0 0;font-size:14px">{links_html}</p>' if links else "")
                + "</div>"
            )


def render_email(content: EmailContent) -> RenderedEmail:
    parts = [_block_text(b) for b in content.blocks]
    tail = [f"{link.label}: {link.url}" for link in content.footer_links] + list(content.footer)
    if tail:
        parts.append("--\n" + "\n".join(tail))
    text = "\n\n".join(parts) + "\n"

    footer_html = "".join(
        f'<p style="margin:0 0 4px"><a href="{_e(link.url)}" style="color:{LINK_COLOR}">'
        f"{_e(link.label)}</a></p>"
        for link in content.footer_links
    ) + "".join(f'<p style="margin:0 0 4px">{_e(line)}</p>' for line in content.footer)
    html = (
        f'<!doctype html>\n<html lang="{HTML_LANG[content.locale]}">'
        '<head><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        f"<title>{_e(content.subject)}</title></head>"
        f'<body style="margin:0;padding:24px;background:#ffffff;color:{TEXT_COLOR};'
        "font-family:system-ui,-apple-system,'Segoe UI',Roboto,'PingFang SC','Microsoft YaHei',"
        'sans-serif;font-size:16px;line-height:1.5">'
        '<div style="max-width:560px;margin:0 auto">'
        + "".join(_block_html(b) for b in content.blocks)
        + (
            '<hr style="border:none;border-top:1px solid #cbd5e1;margin:24px 0">'
            f'<div style="font-size:13px;color:{MUTED_COLOR}">{footer_html}</div>'
            if footer_html
            else ""
        )
        + "</div></body></html>\n"
    )
    return RenderedEmail(subject=content.subject, text=text, html=html)
