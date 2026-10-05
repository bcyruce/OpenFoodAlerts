"""Parse one openFDA food enforcement record into Notification fields."""

import json
import re
from datetime import UTC, date, datetime, time
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from openfoodalerts.archive import RawRecord
from openfoodalerts.db.connection import Connection
from openfoodalerts.normalize.product_type import openfda_product_type
from openfoodalerts.parse.model import ParsedNotification
from openfoodalerts.parse.run import SourceParser

PARSER_VERSION = "openfda-3"
API_URL = "https://api.fda.gov/food/enforcement.json"
# openFDA dates carry no time zone; FDA is in Maryland, so a date means that day in US Eastern.
FDA_TZ = ZoneInfo("America/New_York")

_DATE_FIELDS = (
    "report_date",
    "recall_initiation_date",
    "center_classification_date",
    "termination_date",
)
_KEPT_FIELDS = (
    "event_id",
    "recalling_firm",
    "city",
    "state",
    "country",
    "code_info",
    "product_quantity",
    "distribution_pattern",
    "voluntary_mandated",
    "initial_firm_notification",
    "more_code_info",
)
_TITLE_END = re.compile(r";|,|\.\s")
TITLE_MAX = 140


def parse_fda_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y%m%d").date()


def fda_date_to_timestamp(day: date | None) -> datetime | None:
    if day is None:
        return None
    return datetime.combine(day, time(), tzinfo=FDA_TZ).astimezone(UTC)


def _title(product_description: str) -> str:
    head = _TITLE_END.split(product_description, maxsplit=1)[0].strip()
    if len(head) < 3:
        head = product_description.strip()
    return head if len(head) <= TITLE_MAX else head[: TITLE_MAX - 1].rstrip() + "…"


def record_url(recall_number: str) -> str:
    return f"{API_URL}?search=recall_number:{quote(f'"{recall_number}"')}"


def parse_record(record: dict[str, Any]) -> ParsedNotification:
    recall_number: str = record["recall_number"]
    description: str = record.get("product_description") or ""
    product_type = openfda_product_type(description)
    fields: dict[str, Any] = {k: record[k] for k in _KEPT_FIELDS if record.get(k)}
    for key in _DATE_FIELDS:
        day = parse_fda_date(record.get(key))
        if day is not None:
            fields[key] = day.isoformat()
    return ParsedNotification(
        source_key=recall_number,
        source_url=record_url(recall_number),
        source_ref=record.get("event_id"),
        title=_title(description) or recall_number,
        published_at=fda_date_to_timestamp(parse_fda_date(record.get("report_date"))),
        notification_type="enforcement report",
        risk_official=record.get("classification"),
        status_official=record.get("status"),
        product_type=product_type,
        product_type_provenance="rule" if product_type else "pending",
        product_text=description or None,
        hazard_text=record.get("reason_for_recall"),
        source_fields=fields,
    )


def _parse_raw(conn: Connection, raw: RawRecord) -> ParsedNotification:
    record: dict[str, Any] = json.loads(raw.body)
    return parse_record(record)


_CLASS_RANK = {"Class III": 1, "Class II": 2, "Class I": 3}


def is_substantial(old: ParsedNotification, new: ParsedNotification) -> bool:
    """FDA rule (spec §10.3): the recall class goes up (III -> II -> I) or distribution changes.

    Other changes, such as a move to Terminated or text fixes, only enter the history.
    """
    upgraded = _CLASS_RANK.get(new.risk_official or "", 0) > _CLASS_RANK.get(
        old.risk_official or "", 0
    )
    redistributed = old.source_fields.get("distribution_pattern") != new.source_fields.get(
        "distribution_pattern"
    )
    return upgraded or redistributed


PARSER = SourceParser(
    source="openfda", version=PARSER_VERSION, parse=_parse_raw, is_substantial=is_substantial
)
