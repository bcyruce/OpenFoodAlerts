"""Reading the review queue (the `review_queue` view, migration 20261025001600) and the
"low confidence" threshold per task (`review_settings`, spec §6.3; ticket 21 picks it).

`min_confidence` is the lowest confidence accepted without review: a current result below
it is queued, abstains always are. Without a setting a task uses DEFAULT_MIN_CONFIDENCE
('medium': only confidence = 'low' is queued, spec §4.1).
"""

import html
import re
from dataclasses import dataclass
from typing import Any

from openfoodalerts.classify.evidence import normalize
from openfoodalerts.classify.tasks import CONFIDENCES
from openfoodalerts.db.connection import Connection

DEFAULT_MIN_CONFIDENCE = "medium"

_QUEUE = """
SELECT * FROM review_queue
WHERE (%(task)s::text IS NULL OR task = %(task)s)
  AND (%(source)s::text IS NULL OR source = %(source)s)
ORDER BY task, source, published_at DESC NULLS LAST, classification_id DESC
LIMIT %(limit)s
"""

_STATS = """
WITH current AS (
    SELECT DISTINCT ON (notification_id, task) task, review_status
    FROM ai_classifications
    ORDER BY notification_id, task, created_at DESC, id DESC
), queued AS (
    SELECT task, count(*) FILTER (WHERE abstained) AS abstained,
        count(*) FILTER (WHERE NOT abstained) AS low_confidence
    FROM review_queue GROUP BY task
)
SELECT c.task, count(*) AS current,
    coalesce(max(q.abstained), 0) AS queued_abstained,
    coalesce(max(q.low_confidence), 0) AS queued_low_confidence,
    count(*) FILTER (WHERE c.review_status = 'approved') AS approved,
    count(*) FILTER (WHERE c.review_status = 'corrected') AS corrected,
    coalesce(max(s.min_confidence), %s) AS min_confidence
FROM current c
LEFT JOIN queued q ON q.task = c.task
LEFT JOIN review_settings s ON s.task = c.task
GROUP BY c.task ORDER BY c.task
"""


@dataclass(frozen=True)
class ReviewStats:
    task: str
    # Notifications with a current result for the task
    current: int
    queued_abstained: int
    queued_low_confidence: int
    # current results reviewed
    approved: int
    corrected: int
    min_confidence: str


def queue_items(
    conn: Connection,
    *,
    task: str | None = None,
    source: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Queued classifications with their Notification text, by task, Source and newest
    publication first."""
    rows: list[dict[str, Any]] = conn.execute(
        _QUEUE, {"task": task, "source": source, "limit": limit}
    ).fetchall()
    return rows


def highlight(text: str, span: str | None) -> str:
    """HTML of `text` (whitespace collapsed, as the evidence check sees it) with every
    occurrence of the evidence span in <mark>."""
    shown = normalize(text)
    needle = normalize(span or "")
    if not needle or needle not in shown:
        return html.escape(shown, quote=False)
    marked = f"<mark>{html.escape(needle, quote=False)}</mark>"
    return marked.join(html.escape(part, quote=False) for part in shown.split(needle))


def thresholds(conn: Connection) -> dict[str, str]:
    rows = conn.execute("SELECT task, min_confidence FROM review_settings ORDER BY task")
    return {r["task"]: r["min_confidence"] for r in rows.fetchall()}


def set_threshold(conn: Connection, task: str, min_confidence: str) -> None:
    """Set a task's threshold and commit."""
    if not re.fullmatch(r"[a-z][a-z0-9_]*", task):
        raise ValueError(f"not a task name: {task!r}")
    if min_confidence not in CONFIDENCES:
        raise ValueError(f"min_confidence must be one of {', '.join(reversed(CONFIDENCES))}")
    conn.execute(
        "INSERT INTO review_settings (task, min_confidence) VALUES (%s, %s)"
        " ON CONFLICT (task) DO UPDATE SET min_confidence = excluded.min_confidence,"
        " updated_at = now()",
        (task, min_confidence),
    )
    conn.commit()


def review_stats(conn: Connection) -> list[ReviewStats]:
    rows = conn.execute(_STATS, (DEFAULT_MIN_CONFIDENCE,)).fetchall()
    return [ReviewStats(**r) for r in rows]
