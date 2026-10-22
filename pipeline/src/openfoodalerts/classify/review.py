"""Human review of AI classifications (spec §6.5, ticket 20).

A reviewer works on the current classification of a (Notification, task), normally one
listed in the `review_queue` view, and either

- approves it: `review_status = 'approved'`, `reviewed_value` = the model's value (so that
  "reviewed" is visible wherever reviewed_value is read, ticket 24); or
- corrects it: `review_status = 'corrected'`, `reviewed_value` = the reviewer's value,
  validated by the task's own `check` exactly like a model output (enum for T1/T2/T4/T5,
  verbatim substring for T3), or a reviewer abstain ("cannot be determined from the text");
- or skips it, which writes nothing (the page keeps a session-only skip list).

Each action sets `reviewed_at`, re-derives the task's derived rows from the effective value
(`effective.rederive`) and commits. Repeating an action with the same result changes
nothing (reviewed_at included); a later different action replaces the earlier one.

Rules:
- Only the current classification can be reviewed. A superseded row (a newer prompt
  version or a changed input exists) is refused with `ReviewError`: the newer row is the
  one that is shown, and it is the one to review.
- A review belongs to its row. When the Notification's text or the prompt changes, the
  classifier writes a new, unreviewed row whose model value is shown (and queued again if
  abstained or low-confidence); the older row keeps its review as history.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

from openfoodalerts.classify.effective import (
    REVIEWER_ABSTAINED,
    Derived,
    current_classification,
    effective_value,
    rederive,
)
from openfoodalerts.classify.evidence import MIN_CHARS, normalize
from openfoodalerts.classify.tasks import ABSTAIN, Task
from openfoodalerts.db.connection import Connection

# fields only the model fills in (T6's `abstain` flag: a reviewer abstains with None)
_MODEL_ONLY = ("evidence_span", "confidence", "abstain")

_NOTIFICATION = """
SELECT s.code AS source, n.title, n.summary_source, n.product_text, n.hazard_text
FROM notifications n JOIN sources s ON s.id = n.source_id
WHERE n.id = %s
"""

_ROW = """
SELECT id, notification_id, task, value, abstained, review_status, reviewed_value,
    reviewed_at
FROM ai_classifications WHERE id = %s
"""

_UPDATE = """
UPDATE ai_classifications SET review_status = %s, reviewed_value = %s, reviewed_at = %s
WHERE id = %s
"""


class ReviewError(ValueError):
    """The review cannot be applied: unknown or superseded row, or an invalid value."""


@dataclass(frozen=True)
class Reviewed:
    classification_id: int
    notification_id: int
    review_status: str
    # the effective value after the review, None when there is none
    value: dict[str, Any] | None
    changed: bool
    derived: Derived


def _current_row(conn: Connection, task: Task, classification_id: int) -> dict[str, Any]:
    row: dict[str, Any] | None = conn.execute(_ROW, (classification_id,)).fetchone()
    if row is None:
        raise ReviewError(f"no AI classification {classification_id}")
    if row["task"] != task.name:
        raise ReviewError(f"classification {classification_id} is {row['task']}, not {task.name}")
    current = current_classification(conn, row["notification_id"], task.name)
    if current is None or current["id"] != classification_id:
        raise ReviewError(
            f"classification {classification_id} is superseded by a newer result"
            " for the same Notification; review that one"
        )
    return row


def _apply(
    conn: Connection,
    task: Task,
    row: dict[str, Any],
    status: str,
    reviewed_value: dict[str, Any],
    now: datetime,
) -> Reviewed:
    changed = (row["review_status"], row["reviewed_value"]) != (status, reviewed_value)
    if changed:
        conn.execute(_UPDATE, (status, Jsonb(reviewed_value), now, row["id"]))
    derived = rederive(conn, task, row["notification_id"])
    conn.commit()
    after = row | {"review_status": status, "reviewed_value": reviewed_value}
    return Reviewed(
        classification_id=row["id"],
        notification_id=row["notification_id"],
        review_status=status,
        value=effective_value(after),
        changed=changed,
        derived=derived,
    )


def approve(conn: Connection, task: Task, classification_id: int, *, now: datetime) -> Reviewed:
    """The model's value (or abstain) is right."""
    row = _current_row(conn, task, classification_id)
    return _apply(conn, task, row, "approved", dict(row["value"]), now)


def value_fields(task: Task) -> dict[str, dict[str, Any]]:
    """The fields of a task's value with their JSON schema: the output schema's properties
    except the model's own `evidence_span` and `confidence` (T1: {"category": enum})."""
    properties: dict[str, dict[str, Any]] = task.output_schema()["properties"]
    return {k: v for k, v in properties.items() if k not in _MODEL_ONLY}


def choices(task: Task, field_name: str) -> tuple[str, ...] | None:
    """A field's allowed values for a reviewer (the enum without abstain), None for text."""
    enum = value_fields(task)[field_name].get("enum")
    return None if enum is None else tuple(str(v) for v in enum if v != ABSTAIN)


def _snapshot(conn: Connection, task: Task, notification_id: int) -> dict[str, str]:
    row = conn.execute(_NOTIFICATION, (notification_id,)).fetchone()
    assert row is not None  # ai_classifications.notification_id is a foreign key
    return task.build_input(row["source"], row)


def check_correction(
    task: Task, value: Mapping[str, Any] | None, snapshot: Mapping[str, str]
) -> dict[str, Any]:
    """The stored form of a reviewer's value, or ReviewError. None is a reviewer abstain.

    The value goes through the task's `check` like a model output with high confidence;
    the evidence requirement is the model's (ADR 0006), so a whole input field stands in for
    the evidence span. Whatever the task checks beyond that (the enum, T3's verbatim
    substring) applies to the reviewer too."""
    if value is None:
        return task.check(None, snapshot, failure=REVIEWER_ABSTAINED).value
    fields = value_fields(task)
    unknown = sorted(set(value) - set(fields))
    if unknown:
        raise ReviewError(f"{task.name} has no field {', '.join(unknown)}")
    if ABSTAIN in value.values():
        return task.check(None, snapshot, failure=REVIEWER_ABSTAINED).value
    evidence = next((v for v in snapshot.values() if len(normalize(v)) >= MIN_CHARS), None)
    if evidence is None:
        raise ReviewError("the Notification has no text to check the value against")
    verdict = task.check(
        {**value, "evidence_span": evidence, "confidence": "high"}, snapshot, failure=None
    )
    if verdict.abstained:
        shown = ", ".join(f"{k} = {v!r}" for k, v in value.items())
        raise ReviewError(f"not a valid {task.name} value ({verdict.abstain_reason}): {shown}")
    return verdict.value


def correct(
    conn: Connection,
    task: Task,
    classification_id: int,
    value: Mapping[str, Any] | None,
    *,
    now: datetime,
) -> Reviewed:
    """The right value is `value` (validated, see `check_correction`); None: the text does
    not say (a reviewer abstain, no derived rows)."""
    row = _current_row(conn, task, classification_id)
    reviewed = check_correction(task, value, _snapshot(conn, task, row["notification_id"]))
    if not row["abstained"] and reviewed == row["value"]:
        # the model's own value: an approval
        return _apply(conn, task, row, "approved", reviewed, now)
    return _apply(conn, task, row, "corrected", reviewed, now)
