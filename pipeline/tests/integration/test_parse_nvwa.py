"""NVWA archive -> parse -> Notifications and versions (spec §4.4, §10.3)."""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from openfoodalerts.archive import archive
from openfoodalerts.db.connection import Connection
from openfoodalerts.parse.run import parse, replay

KEY = "/actueel/nieuws/2026/10/13/veiligheidswaarschuwing-cook-korianderzaad-gemalen"
UPDATE = re.compile(rb"<strong>Update[^<]*</strong>(<br>\s*)*")


@pytest.fixture
def page(fixtures_dir: Path) -> bytes:
    return (fixtures_dir / "nvwa" / "detail" / "cook-korianderzaad-update.html").read_bytes()


def without_update(html: bytes) -> bytes:
    stripped, n = UPDATE.subn(b"", html, count=1)
    assert n == 1
    return stripped


def observe(db: Connection, html: bytes, item_id: str = "doc-6ace2f2111495c31eec9e5cd") -> None:
    item = {"id": {"raw": item_id}, "url": {"raw": KEY}}
    archive(
        db,
        source="nvwa",
        kind="list",
        source_key=KEY,
        url="https://www.nvwa.nl/api/search",
        http_status=200,
        content_type="application/json",
        body=json.dumps(item).encode(),
    )
    archive(
        db,
        source="nvwa",
        kind="detail",
        source_key=KEY,
        url=f"https://www.nvwa.nl{KEY}",
        http_status=200,
        content_type="text/html; charset=utf-8",
        body=html,
    )
    db.commit()
    parse(db, ["nvwa"])


def notification(db: Connection) -> dict[str, Any]:
    row = db.execute("SELECT * FROM notifications WHERE source_key = %s", (KEY,)).fetchone()
    assert row is not None
    return row


def versions(db: Connection) -> list[dict[str, Any]]:
    return db.execute(
        "SELECT version, changed_fields, is_substantial FROM notification_versions ORDER BY version"
    ).fetchall()


def test_parse_writes_the_warning(db: Connection, page: bytes) -> None:
    observe(db, page)
    n = notification(db)
    assert n["source_ref"] == "doc-6ace2f2111495c31eec9e5cd"
    assert n["source_url"] == f"https://www.nvwa.nl{KEY}"
    assert n["title"] == "Veiligheidswaarschuwing Cook korianderzaad gemalen"
    assert n["product_type"] == "food"
    assert n["product_type_provenance"] == "rule"
    assert n["risk_official"] is None  # NVWA does not grade: "not graded" (ADR 0006)
    assert n["search_tsv"] is None
    assert n["source_fields"]["update_notes"][0].startswith("Update 13 oktober 2026")


def test_a_new_update_note_is_a_substantial_change(db: Connection, page: bytes) -> None:
    observe(db, without_update(page))
    observe(db, page)
    v1, v2 = versions(db)
    assert v1["is_substantial"] is False
    assert v2["is_substantial"] is True
    assert "source_fields.update_notes" in v2["changed_fields"]
    assert notification(db)["current_version"] == 2


def test_other_changes_only_enter_the_history(db: Connection, page: bytes) -> None:
    observe(db, page)
    observe(db, page.replace(b"Gebruik het korianderzaad niet.", b"Gebruik het niet."))
    _, v2 = versions(db)
    assert v2["is_substantial"] is False
    assert set(v2["changed_fields"]) == {"summary_source"}


def test_rewording_an_existing_update_note_is_not_substantial(db: Connection, page: bytes) -> None:
    observe(db, page)
    observe(db, page.replace(b"artikelnummer 10749.</strong>", b"artikelnr. 10749.</strong>"))
    _, v2 = versions(db)
    assert v2["is_substantial"] is False


def test_replay_reproduces_the_history(db: Connection, page: bytes) -> None:
    observe(db, without_update(page))
    observe(db, page)
    before = versions(db)
    replay(db, ["nvwa"])
    assert versions(db) == before
