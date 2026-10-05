"""Normalized Notification fields produced by every Source parser."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ProductType = Literal["food", "feed", "food contact material", "non-food"]
ProductTypeProvenance = Literal["official", "rule", "ai", "pending"]

# Product types shown on the site, in statistics and in email (spec §4.2-4.3).
SHOWN_PRODUCT_TYPES: tuple[ProductType, ...] = ("food", "feed", "food contact material")


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
