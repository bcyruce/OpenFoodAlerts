"""NVWA site search API request encoding and response reading (spec §3.2)."""

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from openfoodalerts.http import PoliteClient
from openfoodalerts.sources.nvwa import api

# JSON.stringify(...) of the same body and its SHA-256, computed with Node.js.
JS_BODY_ARCHIVE_PAGE_2 = (
    '{"requestState":{"current":2,"filters":[{"field":"topic","values":'
    '["Veiligheidswaarschuwingen"],"type":"all"},{"field":"content_type","values":'
    '["pro:downloadDocument"],"type":"all"}],"resultsPerPage":100,"searchTerm":"",'
    '"sortDirection":"","sortField":"","sortList":[]},"queryConfig":{"filters":[{"field":'
    '"topic","values":["Veiligheidswaarschuwingen"],"type":"all"},{"field":"content_type",'
    '"values":["pro:downloadDocument"],"type":"all"}],"result_fields":{"id":{"raw":{}},'
    '"url":{"raw":{}},"page_title":{"raw":{}},"meta_description":{"raw":{}},'
    '"publication_date":{"raw":{}},"sort_date":{"raw":{}},"information_type":{"raw":{}}},'
    '"disjunctiveFacets":["information_type"],"facets":{"information_type":{"type":"value",'
    '"size":100}},"sortList":[{"field":"sort_date","direction":"desc"}]}}'
)
JS_HASH_ARCHIVE_PAGE_2 = "2c04c7b16bdaa036b5d8e0f90968bbbf961d84b59550c3b528d4e742314e132f"


def test_request_body_and_hash_match_the_websites_json_stringify() -> None:
    request = api.search_request(api.ARCHIVE, page=2)
    assert request.body.decode() == JS_BODY_ARCHIVE_PAGE_2
    assert request.hash == JS_HASH_ARCHIVE_PAGE_2
    assert request.url == f"https://www.nvwa.nl/api/search?hash={JS_HASH_ARCHIVE_PAGE_2}"


def test_non_ascii_is_encoded_like_javascript() -> None:
    assert api.js_stringify({"q": "café", "n": [1, None]}) == '{"q":"café","n":[1,null]}'.encode()


def test_sitemap_page_maps_paths_to_lastmod(fixtures_dir: Path) -> None:
    entries = api.parse_sitemap((fixtures_dir / "nvwa" / "sitemap_1.xml").read_bytes())
    assert len(entries) == 100
    pokebowl = (
        "/actueel/nieuws/2026/10/24/veiligheidswaarschuwing-ah-pokebowl-sticky-tempeh-allergenen"
    )
    assert entries[pokebowl] == datetime(2026, 10, 24, 14, 46, 9, 586000, tzinfo=UTC)
    assert all(path.startswith("/") for path in entries)


def test_fetch_page_posts_filters_in_request_state_and_reads_items(fixtures_dir: Path) -> None:
    payload = (fixtures_dir / "nvwa" / "list_news_p1.json").read_bytes()
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=payload, headers={"Content-Type": "application/json"})

    client = PoliteClient(transport=httpx.MockTransport(handler), sleep=lambda s: None)
    page = api.fetch_page(client, api.NEWS, page=1)

    [request] = seen
    sent = json.loads(request.content)
    assert sent["requestState"]["filters"][1] == {
        "field": "content_type",
        "values": ["pro:newsDocument"],
        "type": "all",
    }
    assert request.url.params["hash"] == api.search_request(api.NEWS, page=1).hash
    assert (page.total_results, page.total_pages) == (66, 1)
    assert len(page.items) == 66
    first = page.items[0]
    assert first.id == "doc-6adcc4b711495c1361ca4af2"
    assert first.path == (
        "/actueel/nieuws/2026/10/24/veiligheidswaarschuwing-ah-pokebowl-sticky-tempeh-allergenen"
    )
    assert first.fields["page_title"] == (
        "Veiligheidswaarschuwing AH Pokebowl sticky tempeh (allergenen)"
    )
