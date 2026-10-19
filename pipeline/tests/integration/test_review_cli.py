"""`ofa review-stats` and `ofa review-threshold`."""

import pytest
from typer.testing import CliRunner

from openfoodalerts.cli import app
from openfoodalerts.db.connection import Connection
from tests.integration.test_review_queue import add_classification, notification

pytestmark = pytest.mark.db
runner = CliRunner()


def test_review_stats_prints_the_queue_per_task(db: Connection) -> None:
    add_classification(db, notification(db, "a"), category=None)
    add_classification(db, notification(db, "b"), confidence="low")
    add_classification(db, notification(db, "c"), confidence="high", review_status="approved")
    db.commit()
    result = runner.invoke(app, ["review-stats"])
    assert result.exit_code == 0, result.output
    assert (
        "hazard_category: 3 current, queued 2 (1 abstained, 1 below medium);"
        " reviewed 1 (1 approved, 0 corrected)"
    ) in result.output


def test_review_stats_without_results(db: Connection) -> None:
    result = runner.invoke(app, ["review-stats"])
    assert result.exit_code == 0, result.output
    assert "no AI classifications" in result.output


def test_review_threshold_shows_and_sets_the_threshold(db: Connection) -> None:
    shown = runner.invoke(app, ["review-threshold", "hazard_category"])
    assert shown.exit_code == 0, shown.output
    assert "hazard_category: min_confidence medium (default)" in shown.output
    set_ = runner.invoke(app, ["review-threshold", "hazard_category", "high"])
    assert set_.exit_code == 0, set_.output
    assert "hazard_category: min_confidence high" in set_.output
    assert db.execute("SELECT min_confidence FROM review_settings").fetchone() == {
        "min_confidence": "high"
    }
    bad = runner.invoke(app, ["review-threshold", "hazard_category", "none"])
    assert bad.exit_code == 2
    assert "must be one of low, medium, high" in bad.output
