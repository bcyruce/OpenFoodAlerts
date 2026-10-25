"""Parse one RASFF Window notification detail into Notification fields (spec §3.1, §4.2).

`additionalInformations` (authority contact persons and emails) is never read: it stays in
`raw_records` only (ADR 0004, spec §11).
"""

import json
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from openfoodalerts.archive import RawRecord
from openfoodalerts.db.connection import Connection
from openfoodalerts.parse.model import (
    CountryRole,
    ParsedCountry,
    ParsedHazard,
    ParsedMeasure,
    ParsedNotification,
    ParsedProductCategory,
    ProductType,
)
from openfoodalerts.parse.run import SourceParser
from openfoodalerts.sources.rasff.lookups import Dictionary, lookup

PARSER_VERSION = "rasff-2"
NOTIFICATION_PAGE_URL = "https://webgate.ec.europa.eu/rasff-window/screen/notification/{notif_id}"

# ecValidationDate and lastUpdate carry no time zone. Assumed to be Brussels local time
# (spec §16 V2, to be verified); `rasff_time` is the only place that depends on it.
RASFF_TZ = ZoneInfo("Europe/Brussels")
RASFF_TIME_FORMAT = "%d-%m-%Y %H:%M:%S"

# notification_type of RASFF News: the official classification name, unchanged. Queries
# recognize News by source = rasff AND notification_type = 'news'.
RASFF_NEWS_TYPE = "news"

# RASFF productType -> Product type (spec §4.2); animals and other are non-food.
_PRODUCT_TYPES: dict[str, ProductType] = {
    "food": "food",
    "feed": "feed",
    "food contact material": "food contact material",
    "animals": "non-food",
    "other": "non-food",
}

_ROLE_FLAGS: dict[str, CountryRole] = {
    "ORIGIN": "origin",
    "NOTIFYING": "notifying",
    "DISTRIBUTION": "distribution",
    "OPERATOR": "operator",
}
_RECIPIENT_FLAGS = {"FOR_ATTENTION": "for_attention", "FOR_FOLLOW_UP": "for_follow_up"}
# RASFF organisations that are not countries, so not missing from the country dictionary:
# "UO" unknown origin, "EU" European Commission, "INFO" INFOSAN.
_NON_COUNTRY_ORGANISATIONS = {"UO", "EU", "INFO"}


def rasff_time(value: str | None) -> datetime | None:
    """A RASFF `dd-mm-yyyy HH:MM:SS` timestamp as an aware UTC datetime."""
    if not value:
        return None
    local = datetime.strptime(value.strip(), RASFF_TIME_FORMAT).replace(tzinfo=RASFF_TZ)
    return local.astimezone(UTC)


def notification_page_url(notif_id: int | str) -> str:
    return NOTIFICATION_PAGE_URL.format(notif_id=notif_id)


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text or None


def _description(value: Any) -> str | None:
    return _clean(value.get("description")) if isinstance(value, dict) else None


def _sampling_date(value: Any) -> date | None:
    """Sampling dates are calendar dates (`dd-mm-yyyy 00:00:00`); no time zone applies."""
    if not isinstance(value, str) or not value.strip():
        return None
    return datetime.strptime(value.strip()[:10], "%d-%m-%Y").date()


def hazard_name(raw_name: str) -> str:
    """`"glycidyl esters  - industrial contaminants"` -> `"glycidyl esters"` (spec §3.1).

    The part before the last ` - ` (the category suffix), whitespace collapsed.
    """
    head = raw_name.rsplit(" - ", 1)[0] if " - " in raw_name else raw_name
    return _clean(head) or _clean(raw_name) or raw_name


def _products(product: dict[str, Any]) -> list[dict[str, Any]]:
    """The main product followed by its `relatedProducts` (which carry their own data)."""
    related = [p for p in product.get("relatedProducts") or [] if isinstance(p, dict)]
    return [product, *related]


def _hazards(products: list[dict[str, Any]], unmapped: set[str]) -> list[ParsedHazard]:
    categories = lookup(Dictionary.HAZARD_CATEGORY)
    hazards = []
    for product in products:
        for h in product.get("hazards") or []:
            raw_name = _clean(h.get("name"))
            if raw_name is None:
                continue
            category_name = _description(h.get("hazardCategory"))
            entry = categories.get_by_name(category_name) if category_name else None
            if category_name and entry is None:
                unmapped.add(category_name)
            hazards.append(
                ParsedHazard(
                    name=hazard_name(raw_name),
                    category_rasff_id=entry.id if entry else None,
                    analytical_result=_clean(h.get("analyticalResult")),
                    unit=_clean(h.get("unit")),
                    max_permitted_level=_clean(h.get("maxPermittedLvl")),
                    sampling_date=_sampling_date(h.get("samplingDate")),
                )
            )
    return hazards


def _countries(
    detail: dict[str, Any], fields: dict[str, Any], unmapped: set[str]
) -> list[ParsedCountry]:
    """Country roles from organizationFlags[].notificationFlags[].flagType.

    FOR_ATTENTION / FOR_FOLLOW_UP are recipients, not roles: kept in source_fields. Flagged
    organisations missing from the country dictionary (e.g. INFOSAN, "INFO") get no role;
    `_NON_COUNTRY_ORGANISATIONS` are not reported as unmapped.
    """
    known = lookup(Dictionary.COUNTRY)
    countries: set[ParsedCountry] = set()
    recipients: dict[str, set[str]] = {}
    for item in detail.get("organizationFlags") or []:
        code = _clean((item.get("organization") or {}).get("code"))
        if code is None:
            continue
        entry = known.get_by_code(code)
        for flag in item.get("notificationFlags") or []:
            flag_type = str(flag.get("flagType") or "")
            if flag_type in _RECIPIENT_FLAGS:
                recipients.setdefault(_RECIPIENT_FLAGS[flag_type], set()).add(code.upper())
            elif flag_type in _ROLE_FLAGS:
                if entry is None or entry.code is None:
                    if code.upper() not in _NON_COUNTRY_ORGANISATIONS:
                        unmapped.add(code.upper())
                else:
                    countries.add(ParsedCountry(iso2=entry.code, role=_ROLE_FLAGS[flag_type]))
    for key, codes in recipients.items():
        fields[key] = sorted(codes)
    return list(countries)


def _product_categories(
    products: list[dict[str, Any]], unmapped: set[str]
) -> list[ParsedProductCategory]:
    known = lookup(Dictionary.PRODUCT_CATEGORY)
    ids: list[int] = []
    for product in products:
        category = product.get("productCategory") or {}
        entry = None
        if isinstance(category.get("id"), int):
            entry = known.get_by_id(category["id"])
        name = _description(category)
        if entry is None and name:
            entry = known.get_by_name(name)
        if entry is None:
            if name:
                unmapped.add(name)
        elif entry.id not in ids:
            ids.append(entry.id)
    return [ParsedProductCategory(rasff_id=i) for i in ids]


def _measures(products: list[dict[str, Any]], unmapped_countries: set[str]) -> list[ParsedMeasure]:
    known = lookup(Dictionary.COUNTRY)
    measures = []
    for product in products:
        for m in product.get("measures") or []:
            code = _clean((m.get("takenBy") or {}).get("isoCode"))
            entry = known.get_by_code(code) if code else None
            if code and entry is None:
                unmapped_countries.add(code.upper())
            action = m.get("actionTaken") or {}
            measures.append(
                ParsedMeasure(
                    country_iso2=entry.code if entry else None,
                    action_rasff_id=action.get("id") if isinstance(action.get("id"), int) else None,
                    action_text=_description(action),
                )
            )
    return measures


def _product_description(item: dict[str, Any]) -> dict[str, str]:
    """Packaging, batch labelling, weight and temperature of one product description."""
    weight = _clean(item.get("weight"))
    unit = _description(item.get("weightUnit"))
    out = {
        "aspect": _clean(item.get("productAspect")),
        "labelling": _clean(item.get("labelling")),
        "weight": f"{weight} {unit}" if weight and unit else weight,
        "temperature": _description(item.get("temperature")),
    }
    return {k: v for k, v in out.items() if v}


def _followups(detail: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for f in detail.get("followups") or []:
        item = {
            "number": f.get("fupNumber"),
            "date": _clean(f.get("fupDate")),
            "type": _description(f.get("fupType")),
            "by": _clean(f.get("organizationCode")),
        }
        out.append({k: v for k, v in item.items() if v is not None})
    return out


def _source_fields(detail: dict[str, Any], products: list[dict[str, Any]]) -> dict[str, Any]:
    """Official fields without a column of their own (never additionalInformations)."""
    product, related = products[0], products[1:]
    risk = detail.get("risk") or {}
    fields: dict[str, Any] = {
        "notification_basis": _description(detail.get("notificationBasis")),
        "distribution_status": _description(product.get("distributionStatus")),
        "hazard_observed": _clean(risk.get("hazardObserved")),
        "persons_affected": risk.get("numberOfPersonsAffected"),
        "product_descriptions": [
            d
            for d in (_product_description(i) for i in product.get("productDescriptions") or [])
            if d
        ],
        "related_products": [
            {
                k: v
                for k, v in {
                    "description": _clean(p.get("description")),
                    "product_category": _description(p.get("productCategory")),
                    "distribution_status": _description(p.get("distributionStatus")),
                }.items()
                if v
            }
            for p in related
        ],
        "followups": _followups(detail),
    }
    return {k: v for k, v in fields.items() if v not in (None, [], "")}


def is_rasff_news(parsed: ParsedNotification) -> bool:
    """RASFF News: shown and searchable, but excluded from statistics (spec §4.3)."""
    return parsed.notification_type == RASFF_NEWS_TYPE


def parse_detail(detail: dict[str, Any]) -> ParsedNotification:
    notif_id = detail["id"]
    product: dict[str, Any] = detail.get("product") or {}
    product_type_name = (_description(detail.get("productType")) or "").casefold()
    product_type = _PRODUCT_TYPES.get(product_type_name)
    products = _products(product)
    unmapped_hazard_categories: set[str] = set()
    unmapped_product_categories: set[str] = set()
    unmapped_countries: set[str] = set()
    hazards = _hazards(products, unmapped_hazard_categories)
    categories = _product_categories(products, unmapped_product_categories)
    measures = _measures(products, unmapped_countries)
    fields = _source_fields(detail, products)
    countries = _countries(detail, fields, unmapped_countries)
    for key, values in (
        ("unmapped_hazard_categories", unmapped_hazard_categories),
        ("unmapped_product_categories", unmapped_product_categories),
        ("unmapped_countries", unmapped_countries),
    ):
        if values:
            fields[key] = sorted(values)
    return ParsedNotification(
        source_key=detail["reference"],
        source_url=notification_page_url(notif_id),
        source_ref=str(notif_id),
        title=_clean(detail.get("subject")) or detail["reference"],
        published_at=rasff_time(detail.get("ecValidationDate")),
        source_updated_at=rasff_time(detail.get("lastUpdate")),
        notification_type=_description(detail.get("notificationClassification")) or "unknown",
        risk_official=_clean((detail.get("risk") or {}).get("riskDecision")),
        status_official=_clean(detail.get("notificationStatus")),
        product_type=product_type,
        product_type_provenance="official" if product_type else "pending",
        product_text=_clean(product.get("description")),
        hazard_text="; ".join(h.name for h in hazards) or None,
        source_fields=fields,
        hazards=hazards,
        product_categories=categories,
        countries=countries,
        measures=measures,
    )


def _parse_raw(conn: Connection, raw: RawRecord) -> ParsedNotification:
    return parse_detail(json.loads(raw.body))


def _distribution(n: ParsedNotification) -> set[str]:
    return {c.iso2 for c in n.countries if c.role == "distribution"}


def is_substantial(old: ParsedNotification, new: ParsedNotification) -> bool:
    """RASFF rule (spec §10.3): a new distribution country, or the risk decision changed."""
    return bool(_distribution(new) - _distribution(old)) or old.risk_official != new.risk_official


PARSER = SourceParser(
    source="rasff", version=PARSER_VERSION, parse=_parse_raw, is_substantial=is_substantial
)
