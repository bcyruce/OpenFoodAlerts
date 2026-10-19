"""The effective value of an AI classification, and the derived rows written from it.

spec §6.5: a reviewer's value overrides the model's. Everything that turns an
ai_classifications row into something shown or matched (notification_hazards,
notification_product_categories, notification_countries; badges and the Digest read
reviewed_value themselves) goes through `effective_value`:

- `corrected`: the reviewer's `reviewed_value`;
- `approved` or `unreviewed`: the model's `value`;
- no value (None) when that value is an abstain: an abstained, uncorrected row, or a
  reviewer's correction to "cannot be determined" (a value with `abstain_reason`, as the
  task's own abstain values have).

Derived rows: `write_derived` replaces the AI rows that a Notification has from one task
with the rows for one classification's effective value; `rederive` does that for the
Notification's current classification (the newest row of the task). Both `ofa classify`
(after storing a new row) and the review actions (after a review) call them, so a derived
row always reflects the current classification's effective value. A task writes derived
rows through its entry in `WRITERS` (T1: the AI primary hazard); a task without one has no
derived rows (T5 is internal, T6 is read from ai_classifications directly).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from openfoodalerts.classify.tasks import HazardCategoryTask, Task
from openfoodalerts.db.connection import Connection
from openfoodalerts.sources.rasff.lookups import normalize_name

# A value with this key is an abstain (Task.check / openfoodalerts.classify.tasks.abstain).
ABSTAIN_REASON = "abstain_reason"

# The current classification of a Notification for a task: the newest row.
CURRENT_SQL = """
SELECT id, notification_id, task, value, abstained, review_status, reviewed_value
FROM ai_classifications
WHERE notification_id = %s AND task = %s
ORDER BY created_at DESC, id DESC
LIMIT 1
"""

# Derived rows a Notification has from one task, in every derived table.
_DERIVED_TABLES = (
    "notification_hazards",
    "notification_product_categories",
    "notification_countries",
)
_DELETE_DERIVED = """
DELETE FROM {table} d
USING ai_classifications c
WHERE d.notification_id = %s AND d.provenance = 'ai' AND c.id = d.ai_classification_id
  AND c.task = %s
"""

_INSERT_HAZARD = """
INSERT INTO notification_hazards (notification_id, position, hazard_name,
    hazard_category_id, is_primary, provenance, ai_classification_id)
VALUES (%s, 0, NULL, %s, true, 'ai', %s)
"""


def is_abstain(value: Mapping[str, Any]) -> bool:
    return value.get(ABSTAIN_REASON) is not None


def effective_value(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """The value that counts for an ai_classifications row (keys value, abstained,
    review_status, reviewed_value), or None when there is none."""
    if row["review_status"] == "corrected":
        reviewed: dict[str, Any] = row["reviewed_value"]
        return None if is_abstain(reviewed) else dict(reviewed)
    if row["abstained"]:
        return None
    return dict(row["value"])


@dataclass
class Derived:
    """What `write_derived` wrote: rows, and values that have no derived row (T1 `other`).
    `lookups` caches value -> id lookups across calls of one run."""

    written: int = 0
    unmapped: int = 0
    lookups: dict[str, int | None] = field(default_factory=dict)


def primary_category(conn: Connection, task: HazardCategoryTask, label: str) -> int | None:
    """hazard_categories.id for a T1 label.

    A label of one RASFF Hazard category maps to it. A merged label maps to the category
    of the same name ("GMO / novel food" -> RASFF 21806 "GMO / novel food", not "novel
    food" or "genetically modified"). `other` merges unrelated small categories
    (packaging, controls, biotoxins), so it has no category: no notification_hazards row,
    the result stays in ai_classifications.
    """
    rasff_ids = task.taxonomy.category_ids(label)
    if not rasff_ids:
        return None
    rows = conn.execute(
        "SELECT id, rasff_id, name_en FROM hazard_categories WHERE rasff_id = ANY(%s)",
        (list(rasff_ids),),
    ).fetchall()
    if len(rasff_ids) == 1:
        return rows[0]["id"] if rows else None
    same_name = [r for r in rows if normalize_name(r["name_en"]) == normalize_name(label)]
    return same_name[0]["id"] if len(same_name) == 1 else None


def _write_primary_hazard(
    conn: Connection,
    task: Task,
    notification_id: int,
    classification_id: int,
    value: Mapping[str, Any],
    out: Derived,
) -> None:
    """T1: the AI primary hazard (provenance ai, is_primary, hazard_name NULL)."""
    assert isinstance(task, HazardCategoryTask)
    label = value.get("category")
    if not isinstance(label, str):
        return
    if label not in out.lookups:
        out.lookups[label] = primary_category(conn, task, label)
    category_id = out.lookups[label]
    if category_id is None:
        out.unmapped += 1
        return
    conn.execute(_INSERT_HAZARD, (notification_id, category_id, classification_id))
    out.written += 1


Writer = Callable[[Connection, Task, int, int, Mapping[str, Any], Derived], None]
# task name -> the function that writes its derived rows (ticket 17 adds T2 / T4 here)
WRITERS: dict[str, Writer] = {HazardCategoryTask.name: _write_primary_hazard}


def write_derived(
    conn: Connection,
    task: Task,
    notification_id: int,
    classification_id: int,
    value: Mapping[str, Any] | None,
    out: Derived | None = None,
) -> Derived:
    """Replace the Notification's derived AI rows of `task` with those of `value` (an
    effective value; None removes them). Does not commit."""
    out = out if out is not None else Derived()
    for table in _DERIVED_TABLES:
        conn.execute(_DELETE_DERIVED.format(table=table), (notification_id, task.name))
    writer = WRITERS.get(task.name)
    if value is not None and writer is not None:
        writer(conn, task, notification_id, classification_id, value, out)
    return out


def current_classification(
    conn: Connection, notification_id: int, task: str
) -> dict[str, Any] | None:
    row: dict[str, Any] | None = conn.execute(CURRENT_SQL, (notification_id, task)).fetchone()
    return row


def rederive(
    conn: Connection, task: Task, notification_id: int, out: Derived | None = None
) -> Derived:
    """Rewrite the derived rows of `task` from the Notification's current classification's
    effective value (none left when it has no classification). Does not commit. Pass the
    same `out` across calls to add up the counts and share the lookups."""
    current = current_classification(conn, notification_id, task.name)
    if current is None:
        return write_derived(conn, task, notification_id, 0, None, out)
    value = effective_value(current)
    return write_derived(conn, task, notification_id, current["id"], value, out)
