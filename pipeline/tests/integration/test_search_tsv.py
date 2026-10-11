"""`search_tsv` is written when a Notification is parsed (spec §4.1, ticket 22).

Matching goes through `notification_search_query(q)`, the SQL function the website uses,
so these tests describe what a visitor's search finds.
"""

import json
from pathlib import Path
from typing import Any

from openfoodalerts.archive import archive
from openfoodalerts.db.connection import Connection
from openfoodalerts.parse.run import parse
from openfoodalerts.sources.openfda.ingest import canonical_json

NVWA_KEY = "/actueel/nieuws/2026/10/13/veiligheidswaarschuwing-cook-korianderzaad-gemalen"


def found(db: Connection, q: str) -> list[str]:
    rows = db.execute(
        """
        SELECT source_key FROM notifications
        WHERE search_tsv @@ notification_search_query(%s) ORDER BY source_key
        """,
        (q,),
    ).fetchall()
    return [r["source_key"] for r in rows]


def put_openfda(db: Connection, record: dict[str, Any]) -> None:
    archive(
        db,
        source="openfda",
        kind="detail",
        source_key=record["recall_number"],
        url="https://api.fda.gov/food/enforcement.json",
        http_status=200,
        content_type="application/json",
        body=canonical_json(record),
    )
    db.commit()


def openfda_record(fixtures_dir: Path, key: str) -> dict[str, Any]:
    body = json.loads((fixtures_dir / "openfda" / "page_recent.json").read_text(encoding="utf-8"))
    record: dict[str, Any] = next(r for r in body["results"] if r["recall_number"] == key)
    return record


def put_rasff(db: Connection, fixtures_dir: Path, notif_id: int) -> None:
    path = fixtures_dir / "rasff" / "details" / f"{notif_id}.json"
    body = json.loads(path.read_text(encoding="utf-8"))
    archive(
        db,
        source="rasff",
        kind="detail",
        source_key=body["reference"],
        url=f"https://example.test/notification/view/id/{notif_id}/en/",
        http_status=200,
        content_type="application/json",
        body=json.dumps(body, ensure_ascii=False).encode(),
    )
    db.commit()


def put_nvwa(db: Connection, fixtures_dir: Path) -> None:
    html = (fixtures_dir / "nvwa" / "detail" / "cook-korianderzaad-update.html").read_bytes()
    archive(
        db,
        source="nvwa",
        kind="detail",
        source_key=NVWA_KEY,
        url=f"https://www.nvwa.nl{NVWA_KEY}",
        http_status=200,
        content_type="text/html; charset=utf-8",
        body=html,
    )
    db.commit()


def test_openfda_notifications_are_found_by_product_and_reason(
    db: Connection, fixtures_dir: Path
) -> None:
    put_openfda(db, openfda_record(fixtures_dir, "H-0015-2027"))
    parse(db, ["openfda"])
    assert found(db, "queso palmita") == ["H-0015-2027"]
    # English stemming: "milks" and "undeclared" match "Undeclared milk".
    assert found(db, "undeclared milks") == ["H-0015-2027"]
    assert found(db, "ethylene oxide") == []


def test_rasff_notifications_are_found_by_hazard_reference_and_unaccented_words(
    db: Connection, fixtures_dir: Path
) -> None:
    put_rasff(db, fixtures_dir, 881995)  # 2026.9489, glycidol in krupuk from China
    put_rasff(db, fixtures_dir, 881658)  # 2026.9458, aflatoxins in dried figs from Türkiye
    parse(db, ["rasff"])
    assert found(db, "glycidol") == ["2026.9489"]
    assert found(db, "2026.9458") == ["2026.9458"]
    assert found(db, "turkiye") == ["2026.9458"]
    assert found(db, "aflatoxin") == ["2026.9458"]
    # websearch syntax: quoted phrases and OR
    assert found(db, '"dried figs" OR krupuk') == ["2026.9458", "2026.9489"]


def test_nvwa_notifications_are_found_with_dutch_stemming(
    db: Connection, fixtures_dir: Path
) -> None:
    put_nvwa(db, fixtures_dir)
    parse(db, ["nvwa"])
    assert found(db, "korianderzaden") == [NVWA_KEY]
    assert found(db, "Cook gemalen") == [NVWA_KEY]


def test_a_changed_notification_gets_a_new_search_document(
    db: Connection, fixtures_dir: Path
) -> None:
    record = openfda_record(fixtures_dir, "H-0015-2027")
    put_openfda(db, record)
    parse(db, ["openfda"])
    put_openfda(db, {**record, "reason_for_recall": "Product may contain Listeria"})
    parse(db, ["openfda"])
    assert found(db, "listeria") == ["H-0015-2027"]
    assert found(db, "undeclared") == []
