"""Normalized Notification fields produced by every Source parser.

Besides the `notifications` columns, a parser may emit official child records: Hazards,
Product categories, countries with their roles, and measures. They default to empty, so a
Source without them (openFDA, NVWA) needs no changes. AI-made child records are written by
the classifier, never by a parser.
"""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ProductType = Literal["food", "feed", "food contact material", "non-food"]
ProductTypeProvenance = Literal["official", "rule", "ai", "pending"]
ChildProvenance = Literal["official", "ai"]
CountryRole = Literal["origin", "notifying", "distribution", "operator", "recalling_firm"]

# Product types shown on the site, in statistics and in email (spec §4.2-4.3).
SHOWN_PRODUCT_TYPES: tuple[ProductType, ...] = ("food", "feed", "food contact material")


class _Child(BaseModel):
    model_config = ConfigDict(frozen=True)


class ParsedHazard(_Child):
    """One Hazard. `is_primary` is None while it is not determined (spec §16 V11)."""

    name: str
    category_rasff_id: int | None = None
    is_primary: bool | None = None
    analytical_result: str | None = None
    unit: str | None = None
    max_permitted_level: str | None = None
    sampling_date: date | None = None
    provenance: ChildProvenance = "official"


class ParsedProductCategory(_Child):
    rasff_id: int
    provenance: ChildProvenance = "official"


class ParsedCountry(_Child):
    iso2: str
    role: CountryRole
    provenance: ChildProvenance = "official"


class ParsedMeasure(_Child):
    """A measure taken by a country (RASFF only)."""

    country_iso2: str | None = None
    action_rasff_id: int | None = None
    action_text: str | None = None


# ParsedNotification fields stored in child tables rather than in `notifications`.
CHILD_FIELDS = ("hazards", "product_categories", "countries", "measures")


class ParsedNotification(BaseModel):
    source_key: str
    source_url: str
    source_ref: str | None = None
    title: str
    published_at: datetime | None = None
    source_updated_at: datetime | None = None
    notification_type: str
    risk_official: str | None = None
    status_official: str | None = None
    product_type: ProductType | None
    product_type_provenance: ProductTypeProvenance
    product_text: str | None = None
    hazard_text: str | None = None
    summary_source: str | None = None
    source_fields: dict[str, Any] = Field(default_factory=dict)
    # Child records, in source order (countries: sorted and deduplicated).
    hazards: list[ParsedHazard] = Field(default_factory=list)
    product_categories: list[ParsedProductCategory] = Field(default_factory=list)
    countries: list[ParsedCountry] = Field(default_factory=list)
    measures: list[ParsedMeasure] = Field(default_factory=list)

    @field_validator("countries")
    @classmethod
    def _canonical_countries(cls, value: list[ParsedCountry]) -> list[ParsedCountry]:
        """Roles are a set: order by (role, country) so stored and parsed states compare."""
        return sorted(set(value), key=lambda c: (c.role, c.iso2, c.provenance))
