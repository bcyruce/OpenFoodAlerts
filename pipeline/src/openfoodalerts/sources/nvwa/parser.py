"""Parse one NVWA safety warning page into Notification fields (spec §3.2).

The page is server-rendered. Metadata comes from `<script id="elastic-content">` and the
DCTERMS meta tags; the `.intro` block holds the summary paragraph (who warns, the hazard,
the advice), optional bold "Update <date>: ..." notes and links to the companies' recall
pages. The products follow the heading "Om welk(e) product(en) gaat het?": an h2 block of
its own on newer pages, an h3 inside `.intro` on older archive pages. Product lines are
matched loosely by label; lines without a recognised label are kept verbatim in
`product_text`. Images are never copied (their copyright usually lies with the retailer).
The Elastic id is not on the page: it comes from the archived search result.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from selectolax.lexbor import LexborHTMLParser, LexborNode

from openfoodalerts.archive import RawRecord, latest_raw
from openfoodalerts.db.connection import Connection
from openfoodalerts.normalize.product_type import nvwa_product_type
from openfoodalerts.parse.model import ParsedNotification
from openfoodalerts.parse.run import SourceParser
from openfoodalerts.sources.nvwa.api import detail_url

PARSER_VERSION = "nvwa-1"
NOTIFICATION_TYPE = "safety warning"

_PRODUCT_HEADING = re.compile(r"^om\s+welke?\s+product(en)?\s+gaat\s+het", re.IGNORECASE)
_UPDATE = re.compile(r"^update\b", re.IGNORECASE)
_WITHDRAWN = re.compile(r"^veiligheidswaarschuwing\s+ingetrokken\b", re.IGNORECASE)
_LINK_ONLY = re.compile(r"^(zie|bekijk)\b", re.IGNORECASE)
_SPACES = re.compile(r"[ \t\r\f\v\u00a0\u200b]+")
_TRACKING_PARAM = re.compile(r"^(_g[a-z]*|utm_.*|fbclid|gclid)$")

# (key, label pattern). The label is the text before ":" and must start with the pattern
# (a prefix: "batch" covers Batchnummer(s), Batchcode).
_LABELS: tuple[tuple[str, str], ...] = (
    ("name", r"(product(naam|omschrijving)?|naam|omschrijving)\b"),
    ("brand", r"merk"),
    ("best_before", r"ten\s?minste\s+houdbaar|tht|houdbaarheidsdatum|best before"),
    ("use_by", r"te\s+gebruiken\s+tot|tgt|uiterste\s+gebruiksdatum"),
    ("ean", r"streepjescode|ean|barcode|gtin"),
    ("batch", r"batch|lot|partij|charge"),
    ("article_number", r"artikel|art\.?\s?nr|productcode|productnummer"),
    ("model", r"model|type"),
    ("producer", r"producent|fabrikant|geproduceerd|leverancier|importeur"),
    ("sold_period", r"verkoopperiode|verkocht\s+(van|vanaf|tussen|tot|sinds|in\s+de\s+periode)"),
    ("sold_at", r"verkocht|verkooppunt|verkrijgbaar|winkel"),
    ("quantity", r"inhoud|gewicht|verpakking"),
)
_LABEL_RES = tuple((key, re.compile(rf"^({pattern})", re.IGNORECASE)) for key, pattern in _LABELS)
# A colon followed by a digit is a time ("16:00"), not the end of a label.
_COLON_LINE = re.compile(r"^(?P<label>[^:]{1,45}?)\s*:(?!\d)\s*(?P<value>.+)$", re.DOTALL)
# Labels sometimes come without a colon ("Artikelnummer 5333636"); only when a code follows.
_BARE_LINE = re.compile(
    r"^(?P<label>artikelnummer|artikelnr\.?|batchcode|batchnummer|lotnummer|lotcode|"
    r"modelnummer|streepjescode|ean|tht)\s+(?P<value>[0-9].*)$",
    re.IGNORECASE,
)
_SOLD_PERIOD_LINE = re.compile(
    r"^verkocht\b.*\b(van|vanaf|tussen|tot|t/m|sinds)\b.*\d{4}", re.IGNORECASE | re.DOTALL
)
_SOLD_AT_LINE = re.compile(r"\b(verkocht|verkrijgbaar)\s+(bij|via)\s+(?P<value>.+)$", re.IGNORECASE)


def _clean(text: str) -> str:
    lines = (_SPACES.sub(" ", line).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


def _text(node: LexborNode) -> str:
    return _clean(node.text(deep=True, separator="", strip=False))


def _label_key(label: str) -> str | None:
    for key, pattern in _LABEL_RES:
        if pattern.match(label.strip()):
            return key
    return None


def match_label(line: str) -> tuple[str, str, str] | None:
    """(key, label as written, value) for a labelled product line, else None."""
    colon = _COLON_LINE.match(line)
    if colon:
        key = _label_key(colon["label"])
        if key is not None:
            return key, colon["label"].strip(), colon["value"].strip()
    bare = _BARE_LINE.match(line)
    if bare:
        key = _label_key(bare["label"])
        assert key is not None
        return key, bare["label"], bare["value"].strip()
    if _SOLD_PERIOD_LINE.match(line):
        return "sold_period", "", line
    sold_at = _SOLD_AT_LINE.search(line)
    if sold_at:
        return "sold_at", "", sold_at["value"].strip()
    return None


@dataclass
class _Products:
    groups: list[dict[str, Any]] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    heading: str | None = None

    def _current(self) -> dict[str, Any]:
        if not self.groups:
            self.groups.append({"fields": []})
        return self.groups[-1]

    def add_heading(self, text: str) -> None:
        self.heading = text
        self.groups.append({"heading": text, "fields": []})
        self.lines.append(text)

    def add_line(self, line: str) -> None:
        match = match_label(line)
        if match is None:
            self.lines.append(line)
            return
        key, label, value = match
        group = self._current()
        if key == "name":
            if "name" in group or group["fields"]:
                group = (
                    {"fields": []}
                    if self.heading is None
                    else {"heading": self.heading, "fields": []}
                )
                self.groups.append(group)
            group["name"] = value
            self.lines.append(value)
        group["fields"].append({"key": key, "label": label, "value": value})


@dataclass
class _Page:
    summary: list[str] = field(default_factory=list)
    updates: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    products: _Products = field(default_factory=_Products)


def _strip_tracking(url: str) -> str:
    """Drop analytics parameters (e.g. `_gl`); any other link is kept exactly as written."""
    parts = urlsplit(url)
    params = parse_qsl(parts.query, keep_blank_values=True)
    kept = [(k, v) for k, v in params if not _TRACKING_PARAM.match(k)]
    if len(kept) == len(params):
        return url
    return urlunsplit(parts._replace(query=urlencode(kept)))


def _collect_links(node: LexborNode, page: _Page) -> None:
    for a in node.css("a[href]"):
        rel = (a.attributes.get("rel") or "").split()
        href = a.attributes.get("href") or ""
        if "external" in rel and href.startswith("http"):
            url = _strip_tracking(href)
            if url not in page.links:
                page.links.append(url)


def _paragraph_lines(node: LexborNode) -> list[str]:
    return [line for line in _text(node).split("\n") if line]


def _intro_paragraph(node: LexborNode, page: _Page) -> None:
    _collect_links(node, page)
    kept = []
    for line in _paragraph_lines(node):
        if _UPDATE.match(line):
            page.updates.append(line)
        else:
            kept.append(line)
    text = " ".join(kept)
    if text and not _is_link_line(text, node):
        page.summary.append(text)


def _is_link_line(text: str, node: LexborNode) -> bool:
    """ "Zie de website van Jumbo" (a link) or "Zie de website van:" (links follow)."""
    has_link = node.css_first("a[rel~=external]") is not None
    return bool(_LINK_ONLY.match(text)) and (has_link or text.endswith(":"))


def _product_node(node: LexborNode, page: _Page) -> None:
    _collect_links(node, page)
    if node.tag in ("h3", "h4", "h5"):
        page.products.add_heading(_text(node).replace("\n", " "))
        return
    if node.tag in ("ul", "ol"):
        for li in node.css("li"):
            text = _text(li).replace("\n", " ")
            if text:
                page.products.add_line(text)
        return
    for line in _paragraph_lines(node):
        if not _is_link_line(line, node):
            page.products.add_line(line)


def _walk(tree: LexborHTMLParser) -> _Page:
    """Read the rich-text blocks of <main> in order, section by section."""
    page = _Page()
    main = tree.css_first("main") or tree.body
    if main is None:
        return page
    section = "other"
    for block in main.css("div.rich-text"):
        in_intro = any(p.attributes.get("class") == "intro" for p in _ancestors(block))
        if in_intro:
            section = "intro"
        elif section == "intro":
            section = "other"
        for node in block.iter(include_text=False):
            text = _text(node)
            if node.tag in ("h2", "h3") and _PRODUCT_HEADING.match(text):
                section = "products"
                continue
            if node.tag == "h2":
                section = "other"
                continue
            if section == "intro" and node.tag == "p":
                _intro_paragraph(node, page)
            elif section == "intro":
                _collect_links(node, page)
            elif section == "products":
                _product_node(node, page)
    return page


def _ancestors(node: LexborNode) -> list[LexborNode]:
    found = []
    parent = node.parent
    while parent is not None:
        found.append(parent)
        parent = parent.parent
    return found


def _meta(tree: LexborHTMLParser, name: str) -> str | None:
    node = tree.css_first(f'meta[name="{name}"]')
    return None if node is None else node.attributes.get("content")


def _timestamp(value: str | None) -> datetime | None:
    return None if not value else datetime.fromisoformat(value.strip())


def _elastic(tree: LexborHTMLParser) -> dict[str, Any]:
    node = tree.css_first("script#elastic-content")
    if node is None:
        return {}
    data: dict[str, Any] = json.loads(node.text())
    return data


def parse_detail(
    html: bytes, path: str, list_item: dict[str, Any] | None = None
) -> ParsedNotification:
    """Parse a detail page; `list_item` is the archived search result for the same URL."""
    tree = LexborHTMLParser(html.decode("utf-8"))
    for br in tree.css("br"):
        br.replace_with("\n")
    elastic = _elastic(tree)
    page = _walk(tree)
    h1 = tree.css_first("h1")
    title = elastic.get("pageTitle") or (_text(h1).replace("\n", " ") if h1 else "") or path
    item_id = (list_item or {}).get("id", {}).get("raw")
    summary = "\n\n".join(page.summary) or None
    product_text = "\n".join(page.products.lines) or None
    product_type = nvwa_product_type(title, summary, product_text)
    information_type = (elastic.get("informationType") or {}).get("label")
    return ParsedNotification(
        source_key=path,
        source_url=detail_url(path),
        source_ref=item_id,
        title=title,
        published_at=_timestamp(_meta(tree, "DCTERMS.issued") or elastic.get("publicationDate")),
        source_updated_at=_timestamp(_meta(tree, "DCTERMS.modified")),
        notification_type=NOTIFICATION_TYPE,
        product_type=product_type,
        product_type_provenance="rule" if product_type else "pending",
        product_text=product_text,
        summary_source=summary,
        # NVWA has no status field; a withdrawal is published as "Veiligheidswaarschuwing
        # ingetrokken - ...".
        status_official="withdrawn" if _WITHDRAWN.search(title) else None,
        source_fields={
            "content_type": elastic.get("contentType"),
            "information_type": information_type,
            "update_notes": page.updates,
            "recall_links": page.links,
            "products": page.products.groups,
        },
    )


def _parse_raw(conn: Connection, raw: RawRecord) -> ParsedNotification | None:
    if raw.http_status != 200:
        return None
    item = latest_raw(conn, source="nvwa", kind="list", source_key=raw.source_key)
    list_item = None if item is None else json.loads(item.body)
    return parse_detail(raw.body, raw.source_key, list_item)


def _update_key(note: str) -> str:
    """ "Update 13 oktober 2026: ..." -> "update 13 oktober 2026" (text edits keep the key)."""
    return note.split(":", 1)[0].strip().lower()


def is_substantial(old: ParsedNotification, new: ParsedNotification) -> bool:
    """NVWA rule (spec §10.3): a new Update note appeared on the page."""
    before = {_update_key(n) for n in old.source_fields.get("update_notes", [])}
    return any(_update_key(n) not in before for n in new.source_fields.get("update_notes", []))


PARSER = SourceParser(
    source="nvwa", version=PARSER_VERSION, parse=_parse_raw, is_substantial=is_substantial
)
