"""Reading the review queue for the page and `ofa review-stats`; the threshold setting."""

from datetime import UTC, datetime, timedelta

import pytest

from openfoodalerts.classify.review_queue import (
    ReviewStats,
    queue_items,
    review_stats,
    set_threshold,
    thresholds,
)
from openfoodalerts.db.connection import Connection
from tests.integration.test_review_queue import add_classification, notification
from tests.mail_data import add_notification

pytestmark = pytest.mark.db

T = datetime(2026, 10, 24, 8, 0, tzinfo=UTC)


def test_queue_items_by_task_and_source_newest_first(db: Connection) -> None:
    old = add_notification(db, "openfda", "old", first_seen_at=T, published_at=T)
    new = add_notification(
        db, "openfda", "new", first_seen_at=T, published_at=T + timedelta(days=1)
    )
    nvwa = add_notification(db, "nvwa", "n", first_seen_at=T)
    a = add_classification(db, old, category=None)
    b = add_classification(db, new, confidence="low")
    c = add_classification(db, nvwa, category=None)
    d = add_classification(db, nvwa, category=None, task="product_category")
    assert [i["classification_id"] for i in queue_items(db)] == [c, b, a, d]
    assert [i["classification_id"] for i in queue_items(db, source="openfda")] == [b, a]
    assert [i["classification_id"] for i in queue_items(db, task="product_category")] == [d]
    assert [i["classification_id"] for i in queue_items(db, limit=1)] == [c]


def test_the_threshold_is_set_per_task(db: Connection) -> None:
    assert thresholds(db) == {}
    set_threshold(db, "hazard_category", "high")
    set_threshold(db, "product_category", "low")
    set_threshold(db, "hazard_category", "medium")
    assert thresholds(db) == {"hazard_category": "medium", "product_category": "low"}
    with pytest.raises(ValueError, match="one of low, medium, high"):
        set_threshold(db, "hazard_category", "none")
    with pytest.raises(ValueError, match="not a task name"):
        set_threshold(db, "Hazard Category", "low")


def test_review_stats_count_the_queue_and_the_reviews(db: Connection) -> None:
    add_classification(db, notification(db, "a"), category=None)
    add_classification(db, notification(db, "b"), confidence="low")
    add_classification(db, notification(db, "c"), confidence="low")
    add_classification(db, notification(db, "d"), confidence="high")
    add_classification(db, notification(db, "e"), category=None, review_status="approved")
    add_classification(
        db,
        notification(db, "f"),
        review_status="corrected",
        reviewed_value={"category": "allergens"},
    )
    stats = review_stats(db)
    assert stats == [
        ReviewStats(
            task="hazard_category",
            current=6,
            queued_abstained=1,
            queued_low_confidence=2,
            approved=1,
            corrected=1,
            min_confidence="medium",
        )
    ]
