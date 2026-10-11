"""RASFF Window contract (spec §3.1, §3.4): the fields `backfill`/`ingest`/`refresh` and
`parser.parse_detail` rely on. Probe: list page 1 plus one known detail.

Optional fields stay optional (many details lack hazards, measures or a risk block), but
when present they must have the type the parser reads: the parser silently drops values
of an unexpected type, so a retyped field would otherwise go unnoticed.
"""

from typing import Annotated

from pydantic import Field

from openfoodalerts.contracts import Contract, expect_ok, json_body, validate
from openfoodalerts.sources.rasff.client import RasffClient

# A RASFF reference, e.g. 2026.9489 or 2012.0101.
Reference = Annotated[str, Field(pattern=r"^\d{4}\.\d+$")]
# ecValidationDate / lastUpdate: dd-mm-yyyy HH:MM:SS, no time zone.
RasffTime = Annotated[str, Field(pattern=r"^\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2}$")]

# 2026.9489 (glycidol in krupuk), a stable, fully populated detail used by the probe.
PROBE_NOTIF_ID = 881995
PROBE_ITEMS_PER_PAGE = 10


class Described(Contract):
    description: str


class OptionallyDescribed(Contract):
    id: int | None = None
    description: str | None = None


class ListItem(Contract):
    notifId: int
    reference: Reference
    ecValidationDate: RasffTime


class ListPage(Contract):
    notifications: Annotated[list[ListItem], Field(min_length=1)]
    totalPages: int
    totalElements: int


class Hazard(Contract):
    name: str | None
    hazardCategory: Described | None = None
    analyticalResult: str | None = None
    unit: str | None = None
    maxPermittedLvl: str | None = None
    samplingDate: str | None = None


class Country(Contract):
    isoCode: str | None = None


class Measure(Contract):
    takenBy: Country | None = None
    actionTaken: OptionallyDescribed | None = None


class Product(Contract):
    description: str | None = None
    productCategory: OptionallyDescribed | None = None
    hazards: list[Hazard] | None = None
    measures: list[Measure] | None = None
    distributionStatus: OptionallyDescribed | None = None
    relatedProducts: list["Product"] | None = None


class Organization(Contract):
    code: str | None


class NotificationFlag(Contract):
    flagType: str


class OrganizationFlag(Contract):
    organization: Organization
    notificationFlags: list[NotificationFlag]


class Risk(Contract):
    riskDecision: str | None = None
    hazardObserved: str | None = None


class Detail(Contract):
    id: int
    reference: Reference
    subject: str | None
    ecValidationDate: RasffTime
    lastUpdate: RasffTime | None = None
    notificationStatus: str | None = None
    notificationClassification: Described
    notificationBasis: OptionallyDescribed | None = None
    productType: Described
    product: Product
    risk: Risk | None = None
    organizationFlags: list[OrganizationFlag]


def check_list(payload: object) -> ListPage:
    return validate(ListPage, payload, "list")


def check_detail(payload: object) -> Detail:
    return validate(Detail, payload, "detail")


def probe(client: RasffClient) -> None:
    """List page 1 (10 items) and the detail of PROBE_NOTIF_ID; raises on a mismatch."""
    response = expect_ok(client.search(1, PROBE_ITEMS_PER_PAGE), "list")
    check_list(json_body(response, "list"))
    response = expect_ok(client.detail(PROBE_NOTIF_ID), "detail")
    check_detail(json_body(response, "detail"))
