"""NVWA contract (spec §3.2, §3.4): what `ingest`/`backfill` and `parser.parse_detail` rely
on. Probe: search API page 1 (new list) plus one known detail page.

The detail page is HTML, so the contract model describes the features the parser extracts:
the `elastic-content` JSON, the DCTERMS dates, the `.intro` block and the rich-text blocks
inside `<main>`.
"""

import json
from typing import Annotated, Any

from pydantic import AwareDatetime, Field
from selectolax.lexbor import LexborHTMLParser

from openfoodalerts.contracts import (
    Contract,
    ContractViolation,
    expect_ok,
    json_body,
    validate,
)
from openfoodalerts.http import PoliteClient
from openfoodalerts.sources.nvwa.api import NEWS, detail_url, search_request

# An archived page (2023-10-04, Jumbo pennywafels): archive URLs did not change in the 2026
# redesign, so it is the most stable known detail.
PROBE_PATH = "/documenten/2023/10/04/veiligheidswaarschuwing-jumbo-pennywafels"
PROBE_PAGE_SIZE = 10

NonEmpty = Annotated[str, Field(min_length=1)]


class Raw[T](Contract):
    raw: T


class ListResult(Contract):
    id: Raw[NonEmpty]
    url: Raw[Annotated[str, Field(pattern=r"^/")]]
    page_title: Raw[str] | None = None
    sort_date: Raw[str] | None = None


class ListResponse(Contract):
    results: Annotated[list[ListResult], Field(min_length=1)]
    totalResults: int
    totalPages: int


class Elastic(Contract):
    pageTitle: NonEmpty
    publicationDate: str | None = None
    contentType: str | None = None
    informationType: dict[str, Any] | None = None


class DetailPage(Contract):
    elastic: Elastic
    issued: AwareDatetime
    modified: AwareDatetime | None
    intro: Annotated[int, Field(ge=1, description="number of .intro blocks")]
    rich_text_blocks: Annotated[int, Field(ge=1, description="div.rich-text inside <main>")]


def check_list(payload: object) -> ListResponse:
    return validate(ListResponse, payload, "list")


def _meta(tree: LexborHTMLParser, name: str) -> str | None:
    node = tree.css_first(f'meta[name="{name}"]')
    return None if node is None else node.attributes.get("content")


def page_features(html: bytes) -> dict[str, Any]:
    """The parts of a detail page the parser reads, as plain data for the contract model."""
    try:
        text = html.decode("utf-8")
    except UnicodeDecodeError:
        raise ContractViolation("detail: not UTF-8") from None
    tree = LexborHTMLParser(text)
    script = tree.css_first("script#elastic-content")
    elastic = None
    if script is not None:
        try:
            elastic = json.loads(script.text())
        except ValueError:
            raise ContractViolation("detail: elastic-content is not JSON") from None
    main = tree.css_first("main")
    return {
        "elastic": elastic,
        "issued": _meta(tree, "DCTERMS.issued"),
        "modified": _meta(tree, "DCTERMS.modified"),
        "intro": len(tree.css(".intro")),
        "rich_text_blocks": 0 if main is None else len(main.css("div.rich-text")),
    }


def check_detail(html: bytes) -> DetailPage:
    return validate(DetailPage, page_features(html), "detail")


def probe(client: PoliteClient) -> None:
    """Search API page 1 of the new list and the PROBE_PATH page; raises on a mismatch."""
    request = search_request(NEWS, 1, PROBE_PAGE_SIZE)
    response = client.post(
        request.url, content=request.body, headers={"Content-Type": "application/json"}
    )
    check_list(json_body(expect_ok(response, "list"), "list"))
    response = expect_ok(client.get(detail_url(PROBE_PATH)), "detail")
    check_detail(response.content)
