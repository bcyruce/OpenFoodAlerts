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
rows through its entry in `WRITERS`; a task without one has no derived rows (T6 is read
from ai_classifications directly). Every derived row has provenance `ai` and the id of
the classification it came from, so a task only ever replaces its own rows:

- T1 hazard_category: `notification_hazards` position 0, is_primary true, the label's
  hazard_category_id (`primary_category`), hazard_name NULL;
- T2 product_category: `notification_product_categories` position 0, the RASFF Product
  category of that name;
- T3 hazard: its own `notification_hazards` row, position 1, hazard_name = the span,
  hazard_category_id NULL, is_primary NULL (not determined); T1's row is left alone;
- T4 origin_country: `notification_countries` role origin, the ISO2 code if it is in
  `countries`; `unknown` writes nothing;
- T5 product_type (internal, no badge): `notifications.product_type` with provenance ai,
  only where it is `pending` or was set by T5 before (never a rule or official value).
  T5 also writes when there is no value: an abstain counts as food (spec §10.4 "T5 弃权时
  也算"; `T5_NO_VALUE_PRODUCT_TYPE`), so `WRITES_WITHOUT_VALUE` lists it.
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


def _write_product_category(
    conn: Connection,
    task: Task,
    notification_id: int,
    classification_id: int,
    value: Mapping[str, Any],
    out: Derived,
) -> None:
    """T2: the AI Product category (a name of `product_categories`)."""
    name = value.get("category")
    if not isinstance(name, str):
        return
    row = conn.execute(
        "INSERT INTO notification_product_categories (notification_id, position,"
        " product_category_id, provenance, ai_classification_id)"
        " SELECT %s, 0, id, 'ai', %s FROM product_categories WHERE name_en = %s RETURNING id",
        (notification_id, classification_id, name),
    ).fetchone()
    if row is None:
        out.unmapped += 1
    else:
        out.written += 1


def _write_hazard_name(
    conn: Connection,
    task: Task,
    notification_id: int,
    classification_id: int,
    value: Mapping[str, Any],
    out: Derived,
) -> None:
    """T3: the Hazard as the source words it, in a row of its own (T1's row and T3's are
    replaced independently)."""
    hazard = value.get("hazard")
    if not isinstance(hazard, str) or not hazard:
        return
    conn.execute(
        "INSERT INTO notification_hazards (notification_id, position, hazard_name,"
        " hazard_category_id, is_primary, provenance, ai_classification_id)"
        " VALUES (%s, 1, %s, NULL, NULL, 'ai', %s)",
        (notification_id, hazard, classification_id),
    )
    out.written += 1


def _write_origin_country(
    conn: Connection,
    task: Task,
    notification_id: int,
    classification_id: int,
    value: Mapping[str, Any],
    out: Derived,
) -> None:
    """T4: the AI country of origin; `unknown` has no row."""
    country = value.get("country")
    if not isinstance(country, str) or country == "unknown":
        return
    row = conn.execute(
        "INSERT INTO notification_countries (notification_id, country_iso2, role, provenance,"
        " ai_classification_id)"
        " SELECT %s, iso2, 'origin', 'ai', %s FROM countries WHERE iso2 = %s RETURNING id",
        (notification_id, classification_id, country),
    ).fetchone()
    if row is None:
        out.unmapped += 1
    else:
        out.written += 1


# The Product type of a T5 result without a value (spec §10.4: an abstain counts as food).
T5_NO_VALUE_PRODUCT_TYPE = "food"


def _write_product_type(
    conn: Connection,
    task: Task,
    notification_id: int,
    classification_id: int,
    value: Mapping[str, Any],
    out: Derived,
) -> None:
    """T5: notifications.product_type (provenance ai) where the rules left it to T5."""
    kind = value.get("product_type")
    row = conn.execute(
        "UPDATE notifications SET product_type = %s, product_type_provenance = 'ai'"
        " WHERE id = %s AND product_type_provenance IN ('pending', 'ai') RETURNING id",
        (kind if isinstance(kind, str) else T5_NO_VALUE_PRODUCT_TYPE, notification_id),
    ).fetchone()
    if row is not None:
        out.written += 1


Writer = Callable[[Connection, Task, int, int, Mapping[str, Any], Derived], None]
# task name -> the function that writes its derived rows
WRITERS: dict[str, Writer] = {
    HazardCategoryTask.name: _write_primary_hazard,
    "product_category": _write_product_category,
    "hazard": _write_hazard_name,
    "origin_country": _write_origin_country,
    "product_type": _write_product_type,
}
# Tasks whose writer also runs when a classification has no value (it gets {}).
WRITES_WITHOUT_VALUE = frozenset({"product_type"})


def write_derived(
    conn: Connection,
    task: Task,
    notification_id: int,
    classification_id: int,
    value: Mapping[str, Any] | None,
    out: Derived | None = None,
) -> Derived:
    """Replace the Notification's derived AI rows of `task` with those of `value` (an
    effective value; None removes them, except for `WRITES_WITHOUT_VALUE` tasks of an
    existing classification). Does not commit."""
    out = out if out is not None else Derived()
    for table in _DERIVED_TABLES:
        conn.execute(_DELETE_DERIVED.format(table=table), (notification_id, task.name))
    writer = WRITERS.get(task.name)
    if value is None and classification_id and task.name in WRITES_WITHOUT_VALUE:
        value = {}
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
