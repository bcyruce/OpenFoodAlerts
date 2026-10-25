"""`taxonomy-draft --from-db`: the draft counts taken from the parsed RASFF archive."""

import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from openfoodalerts.archive import archive
from openfoodalerts.cli import app
from openfoodalerts.db.connection import Connection
from openfoodalerts.parse.run import parse
from openfoodalerts.sources.rasff.lookups import Dictionary, lookup
from openfoodalerts.sources.rasff.parser import parse_detail
from openfoodalerts.taxonomy import count_hazard_categories_in_db

DETAILS = Path(__file__).parents[1] / "fixtures" / "rasff" / "details"
SHOWN = {"food", "feed", "food contact material"}


def load(db: Connection) -> list[dict]:
    details = [json.loads(p.read_bytes()) for p in sorted(DETAILS.glob("*.json"))]
    for d in details:
        archive(
            db,
            source="rasff",
            kind="detail",
            source_key=d["reference"],
            url="https://webgate.ec.europa.eu/rasff-window/",
            http_status=200,
            content_type="application/json",
            body=json.dumps(d).encode(),
        )
    db.commit()
    parse(db)
    return details


def expected(details: list[dict], since: datetime) -> dict[int, int]:
    """Count straight from the fixtures: once per Notification and category."""
    counts: dict[int, int] = {}
    for d in details:
        n = parse_detail(d)
        if n.product_type not in SHOWN or n.published_at is None or n.published_at < since:
            continue
        for rasff_id in {h.category_rasff_id for h in n.hazards} - {None}:
            assert rasff_id is not None
            counts[rasff_id] = counts.get(rasff_id, 0) + 1
    return counts


def test_counts_each_notification_once_per_category(db: Connection) -> None:
    details = load(db)
    since = datetime(2020, 1, 1, tzinfo=UTC)
    rows = count_hazard_categories_in_db(db, since=since)
    got = {r.rasff_id: r.count for r in rows if r.count}
    assert got == expected(details, since)
    assert got  # the fixtures have official Hazards


def test_every_dictionary_category_is_listed_even_without_notifications(db: Connection) -> None:
    load(db)
    rows = count_hazard_categories_in_db(db, since=datetime(2020, 1, 1, tzinfo=UTC))
    assert {r.rasff_id for r in rows} == {e.id for e in lookup(Dictionary.HAZARD_CATEGORY)}
    assert {r.name for r in rows} == {e.name for e in lookup(Dictionary.HAZARD_CATEGORY)}


def test_since_excludes_older_notifications(db: Connection) -> None:
    details = load(db)
    since = datetime(2026, 1, 1, tzinfo=UTC)
    rows = count_hazard_categories_in_db(db, since=since)
    assert {r.rasff_id: r.count for r in rows if r.count} == expected(details, since)


def test_cli_writes_the_draft_from_the_database(db: Connection, tmp_path: Path) -> None:
    details = load(db)
    out = tmp_path / "draft.csv"
    result = CliRunner().invoke(app, ["taxonomy-draft", "--from-db", "--output", str(out)])
    assert result.exit_code == 0, result.output
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "rasff_id,name_en,notifications_since_2020-01-01,label"
    written = {int(line.split(",")[0]): int(line.split(",")[-2]) for line in lines[1:]}
    assert {k: v for k, v in written.items() if v} == expected(
        details, datetime(2020, 1, 1, tzinfo=UTC)
    )
