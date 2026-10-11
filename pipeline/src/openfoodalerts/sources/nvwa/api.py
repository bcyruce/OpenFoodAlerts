"""NVWA site search API and sitemap (spec §3.2, ADR 0002).

The list of safety warnings comes from the search API the website itself calls. Its body
is the Elastic Search UI `{requestState, queryConfig}` pair; filters only take effect in
`requestState.filters`, and the server rejects a `queryConfig` without facets. The `hash`
query parameter is hex(SHA-256(JSON.stringify(body))); the server does not check it yet,
but we send exactly what the browser would.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree

from openfoodalerts.http import PoliteClient

BASE_URL = "https://www.nvwa.nl"
SEARCH_URL = f"{BASE_URL}/api/search"
TOPIC = "Veiligheidswaarschuwingen"
NEWS = "pro:newsDocument"  # list since 2026-07-01
ARCHIVE = "pro:downloadDocument"  # archive 2023-10-04 .. 2026-06-30
CONTENT_TYPES = (NEWS, ARCHIVE)
PAGE_SIZE = 100
RESULT_FIELDS = (
    "id",
    "url",
    "page_title",
    "meta_description",
    "publication_date",
    "sort_date",
    "information_type",
)
_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def js_stringify(value: Any) -> bytes:
    """UTF-8 bytes of JavaScript's JSON.stringify(value) for plain JSON data."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()


@dataclass(frozen=True)
class SearchRequest:
    body: bytes
    hash: str

    @property
    def url(self) -> str:
        return f"{SEARCH_URL}?hash={self.hash}"


def search_body(content_type: str, page: int, per_page: int = PAGE_SIZE) -> dict[str, Any]:
    filters = [
        {"field": "topic", "values": [TOPIC], "type": "all"},
        {"field": "content_type", "values": [content_type], "type": "all"},
    ]
    return {
        "requestState": {
            "current": page,
            "filters": filters,
            "resultsPerPage": per_page,
            "searchTerm": "",
            "sortDirection": "",
            "sortField": "",
            "sortList": [],
        },
        "queryConfig": {
            "filters": filters,
            "result_fields": {f: {"raw": {}} for f in RESULT_FIELDS},
            "disjunctiveFacets": ["information_type"],
            "facets": {"information_type": {"type": "value", "size": 100}},
            "sortList": [{"field": "sort_date", "direction": "desc"}],
        },
    }


def search_request(content_type: str, page: int, per_page: int = PAGE_SIZE) -> SearchRequest:
    body = js_stringify(search_body(content_type, page, per_page))
    return SearchRequest(body=body, hash=hashlib.sha256(body).hexdigest())


@dataclass(frozen=True)
class ListItem:
    """One search result: `fields` holds the raw values, `raw` the result object as served."""

    id: str
    path: str
    fields: dict[str, Any]
    raw: dict[str, Any]


@dataclass(frozen=True)
class ListPage:
    items: list[ListItem]
    total_results: int
    total_pages: int


def _item(result: dict[str, Any]) -> ListItem:
    fields = {k: v.get("raw") for k, v in result.items() if isinstance(v, dict) and "raw" in v}
    return ListItem(id=str(fields["id"]), path=str(fields["url"]), fields=fields, raw=result)


def read_page(payload: dict[str, Any]) -> ListPage:
    return ListPage(
        items=[_item(r) for r in payload.get("results", [])],
        total_results=int(payload["totalResults"]),
        total_pages=int(payload["totalPages"]),
    )


def fetch_page(
    client: PoliteClient, content_type: str, page: int, per_page: int = PAGE_SIZE
) -> ListPage:
    request = search_request(content_type, page, per_page)
    response = client.post(
        request.url, content=request.body, headers={"Content-Type": "application/json"}
    )
    response.raise_for_status()
    return read_page(response.json())


def detail_url(path: str) -> str:
    return BASE_URL + path


def sitemap_url(page: int) -> str:
    return f"{BASE_URL}/sitemap/{page}.xml"


def parse_sitemap(xml: bytes) -> dict[str, datetime]:
    """URL path -> lastmod for every NVWA URL in one sitemap page."""
    entries: dict[str, datetime] = {}
    for url in ElementTree.fromstring(xml).iter(f"{_SITEMAP_NS}url"):
        loc = url.findtext(f"{_SITEMAP_NS}loc")
        lastmod = url.findtext(f"{_SITEMAP_NS}lastmod")
        if not loc or not lastmod:
            continue
        parts = urlsplit(loc.strip())
        if parts.netloc != urlsplit(BASE_URL).netloc:
            continue
        entries[parts.path] = datetime.fromisoformat(lastmod.strip())
    return entries
