"""openFDA food enforcement contract (spec §3.3, §3.4): what `ingest-openfda` and
`parser.parse_record` rely on. Probe: one request with `limit=1`."""

from typing import Annotated

import httpx
from pydantic import Field

from openfoodalerts.contracts import Contract, expect_ok, json_body, validate
from openfoodalerts.http import PoliteClient
from openfoodalerts.sources.openfda.ingest import _with_key
from openfoodalerts.sources.openfda.parser import API_URL

FdaDate = Annotated[str, Field(pattern=r"^\d{8}$")]


class Totals(Contract):
    total: int


class Meta(Contract):
    last_updated: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    results: Totals


class Record(Contract):
    # A string, possibly empty or "N/A": records not yet classified may lack a number.
    recall_number: str
    product_description: str
    report_date: FdaDate
    recall_initiation_date: FdaDate | None = None
    center_classification_date: FdaDate | None = None
    termination_date: FdaDate | None = None
    classification: str | None = None
    status: str | None = None
    reason_for_recall: str | None = None
    event_id: str | None = None
    distribution_pattern: str | None = None
    recalling_firm: str | None = None


class Page(Contract):
    meta: Meta
    results: Annotated[list[Record], Field(min_length=1)]


def check_page(payload: object) -> Page:
    return validate(Page, payload, "page")


def probe(client: PoliteClient) -> None:
    """`GET food/enforcement.json?limit=1`; raises on a mismatch. A 404 is a violation
    here: openFDA uses it for "no matches", and an unfiltered query always matches."""
    url = str(httpx.URL(API_URL).copy_merge_params(_with_key({"limit": "1"})))
    check_page(json_body(expect_ok(client.get(url), "page"), "page"))
