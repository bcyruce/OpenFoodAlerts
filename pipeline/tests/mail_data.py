"""Builders for Digest / Instant email tests: Notifications with exact timestamps and
classifications, and Subscriptions as the website writes them."""

import hashlib
import hmac
import json
import uuid
from datetime import datetime
from typing import Any

from openfoodalerts.db.connection import Connection

PEPPER = "test-pepper"
SOURCE_IDS = {"rasff": 1, "nvwa": 2, "openfda": 3}


def email_hash(email: str) -> str:
    """As the website stores it (web/lib/subscriptions/crypto.ts)."""
    return hmac.new(PEPPER.encode(), f"email:v1:{email}".encode(), hashlib.sha256).hexdigest()


def add_notification(
    conn: Connection,
    source: str,
    key: str,
    *,
    first_seen_at: datetime,
    title: str | None = None,
    published_at: datetime | None = None,
    product_type: str | None = "food",
    notification_type: str | None = None,
    risk_official: str | None = None,
    hazard_text: str | None = None,
    summary_source: str | None = None,
    source_url: str | None = None,
) -> int:
    raw = conn.execute(
        "INSERT INTO raw_records (source_id, source_key, kind, url, http_status, content_hash,"
        " content_type, body) VALUES (%s, %s, 'detail', 'https://example.test', 200, 'h',"
        " 'application/json', '\\x7b7d') RETURNING id",
        (SOURCE_IDS[source], key),
    ).fetchone()
    assert raw is not None
    default_type = {"rasff": "alert", "nvwa": "safety warning", "openfda": "enforcement report"}
    row = conn.execute(
        """
        INSERT INTO notifications (source_id, source_key, source_url, title, published_at,
            first_seen_at, last_changed_at, notification_type, risk_official, product_type,
            product_type_provenance, hazard_text, summary_source, raw_record_id, parser_version)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'test')
        RETURNING id
        """,
        (
            SOURCE_IDS[source],
            key,
            source_url or f"https://example.test/{source}/{key}",
            title or f"{source} {key}",
            published_at or first_seen_at,
            first_seen_at,
            first_seen_at,
            notification_type or default_type[source],
            risk_official,
            product_type,
            "pending" if product_type is None else "official",
            hazard_text,
            summary_source,
            raw["id"],
        ),
    ).fetchone()
    assert row is not None
    nid: int = row["id"]
    conn.execute(
        "INSERT INTO notification_versions (notification_id, version, raw_record_id,"
        " observed_at) VALUES (%s, 1, %s, %s)",
        (nid, raw["id"], first_seen_at),
    )
    return nid


def add_version(
    conn: Connection, nid: int, version: int, observed_at: datetime, *, substantial: bool
) -> None:
    raw = conn.execute("SELECT raw_record_id FROM notifications WHERE id = %s", (nid,)).fetchone()
    assert raw is not None
    conn.execute(
        "INSERT INTO notification_versions (notification_id, version, raw_record_id,"
        " observed_at, is_substantial) VALUES (%s, %s, %s, %s, %s)",
        (nid, version, raw["raw_record_id"], observed_at, substantial),
    )


def add_hazard(
    conn: Connection, nid: int, rasff_id: int | None, provenance: str = "official"
) -> None:
    conn.execute(
        "INSERT INTO notification_hazards (notification_id, hazard_name, hazard_category_id,"
        " provenance) VALUES (%s, 'h', (SELECT id FROM hazard_categories WHERE rasff_id = %s), %s)",
        (nid, rasff_id, provenance),
    )


def add_product_category(
    conn: Connection, nid: int, rasff_id: int, provenance: str = "official"
) -> None:
    conn.execute(
        "INSERT INTO notification_product_categories (notification_id, product_category_id,"
        " provenance) SELECT %s, id, %s FROM product_categories WHERE rasff_id = %s",
        (nid, provenance, rasff_id),
    )


def add_country(
    conn: Connection, nid: int, iso2: str, role: str = "origin", provenance: str = "official"
) -> None:
    conn.execute(
        "INSERT INTO notification_countries (notification_id, country_iso2, role, provenance)"
        " VALUES (%s, %s, %s, %s)",
        (nid, iso2, role, provenance),
    )


def add_subscription(
    conn: Connection,
    email: str,
    *,
    confirmed_at: datetime,
    locale: str = "en",
    filters: dict[str, Any] | None = None,
    include_unclassified: bool = True,
    status: str = "active",
    instant_sources: list[str] | None = None,
    subscription_id: str | None = None,
) -> str:
    sid = subscription_id or str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO subscriptions (id, email, email_hash, locale, filters, include_unclassified,
            instant_sources, status, manage_token_hash, consent_at, consent_text_version,
            confirmed_at, unsubscribed_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '2026-10-25', %s, %s)
        """,
        (
            sid,
            email,
            email_hash(email),
            locale,
            json.dumps(
                {
                    "sources": [],
                    "hazard_categories": [],
                    "product_categories": [],
                    "origin_countries": [],
                    **(filters or {}),
                }
            ),
            include_unclassified,
            instant_sources or [],
            status,
            uuid.uuid4().hex,
            confirmed_at,
            confirmed_at,
            confirmed_at if status == "unsubscribed" else None,
        ),
    )
    return sid


def suppress(conn: Connection, email: str) -> None:
    conn.execute("INSERT INTO email_suppressions (email_hash) VALUES (%s)", (email_hash(email),))
