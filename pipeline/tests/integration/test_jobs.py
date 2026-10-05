import json

import pytest

from openfoodalerts.db.connection import Connection
from openfoodalerts.jobs import run_job


def source_row(db: Connection) -> dict[str, object]:
    row = db.execute("SELECT * FROM sources WHERE code = 'openfda'").fetchone()
    assert row is not None
    return row


def test_success_logs_one_json_line_and_marks_source_fresh(
    db: Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    with run_job(db, "ingest-openfda", "openfda") as stats:
        stats.new += 2
    line = json.loads(capsys.readouterr().err.strip())
    assert line["job"] == "ingest-openfda"
    assert line["status"] == "ok"
    assert line["new"] == 2
    assert "duration_s" in line
    assert source_row(db)["last_success_at"] is not None


def test_failure_records_last_error_and_reraises(
    db: Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(RuntimeError), run_job(db, "ingest-openfda", "openfda"):
        raise RuntimeError("boom")
    row = source_row(db)
    assert row["last_error"] == "RuntimeError: boom"
    assert row["last_error_at"] is not None
    assert row["last_success_at"] is None
    line = json.loads(capsys.readouterr().err.strip())
    assert line["status"] == "error"
    assert line["errors"] == ["RuntimeError: boom"]
