"""Rows derived from AI classifications: the one write path from `ai_classifications` to the
tables the site, the Digest and the Instant email read.

`apply_current(conn, task, notification_id)` takes the Notification's current result for the
task (the newest `ai_classifications` row of that (notification, task)), computes its
effective value (`effective_value`: a human correction wins over the model, ticket 20) and
replaces what the task derived before:

- T1 hazard_category: `notification_hazards` position 0, is_primary true, the
  hazard_category_id of the label (`primary_category`), hazard_name NULL;
- T2 product_category: `notification_product_categories` position 0, the RASFF Product
  category of that name;
- T3 hazard: `notification_hazards` position 1, hazard_name = the span,
  hazard_category_id NULL, is_primary NULL (not determined);
- T4 origin_country: `notification_countries` role origin, an ISO2 code that is in
  `countries`; `unknown` writes nothing;
- T5 product_type: `notifications.product_type` with provenance ai; an abstain sets food
  (spec §10.4).

Every derived row has provenance `ai` and the `ai_classification_id` it came from, so each
task removes only its own earlier rows (by the classification's task) and a review of one
task never touches another's. Official rows are never touched; T5 changes only Product
types that are `pending` or were set by T5 before (`ai`), never a rule or official one.
An abstained effective value (no answer) writes no row, except for T5.

`ofa classify` calls it after every new result; the review tool (ticket 20) calls it after
writing `review_status` / `reviewed_value`. Tasks without a derived table (T6 summaries,
read from ai_classifications directly) are a no-op.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from openfoodalerts.classify.tasks import HazardCategoryTask, Task
from openfoodalerts.db.connection import Connection
from openfoodalerts.sources.rasff.lookups import normalize_name

# The Product type an abstained T5 result stands for (spec §10.4: "T5 弃权时也算" food).
T5_ABSTAIN_PRODUCT_TYPE = "food"

_CURRENT = """
SELECT id, value, review_status, reviewed_value FROM ai_classifications
WHERE notification_id = %s AND task = %s
ORDER BY created_at DESC, id DESC
LIMIT 1
"""


@dataclass(frozen=True)
class Applied:
    # derived rows (or the Product type) written for the current result
    written: int = 0
    # an answer with no row to write: T1 `other`, an unknown country or category name
    unmapped: int = 0


def effective_value(
    value: Mapping[str, Any], review_status: str, reviewed_value: Mapping[str, Any] | None
) -> Mapping[str, Any]:
    """The value derived tables show: the reviewer's when corrected, else the model's."""
    if review_status == "corrected" and reviewed_value is not None:
        return reviewed_value
    return value


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


def _delete_own(conn: Connection, table: str, notification_id: int, task: str) -> None:
    conn.execute(
        f"""
        DELETE FROM {table} x USING ai_classifications c
        WHERE x.notification_id = %s AND x.provenance = 'ai' AND c.id = x.ai_classification_id
          AND c.task = %s
        """,
        (notification_id, task),
    )


Writer = Callable[[Connection, Task, int, int, Any], Applied]


def _hazard_category(conn: Connection, task: Task, nid: int, cid: int, label: Any) -> Applied:
    _delete_own(conn, "notification_hazards", nid, task.name)
    if label is None:
        return Applied()
    assert isinstance(task, HazardCategoryTask)
    category_id = primary_category(conn, task, str(label))
    if category_id is None:
        return Applied(unmapped=1)
    conn.execute(
        "INSERT INTO notification_hazards (notification_id, position, hazard_name,"
        " hazard_category_id, is_primary, provenance, ai_classification_id)"
        " VALUES (%s, 0, NULL, %s, true, 'ai', %s)",
        (nid, category_id, cid),
    )
    return Applied(written=1)


def _product_category(conn: Connection, task: Task, nid: int, cid: int, name: Any) -> Applied:
    _delete_own(conn, "notification_product_categories", nid, task.name)
    if name is None:
        return Applied()
    row = conn.execute(
        "INSERT INTO notification_product_categories (notification_id, position,"
        " product_category_id, provenance, ai_classification_id)"
        " SELECT %s, 0, id, 'ai', %s FROM product_categories WHERE name_en = %s RETURNING id",
        (nid, cid, str(name)),
    ).fetchone()
    return Applied(written=1) if row else Applied(unmapped=1)


def _hazard(conn: Connection, task: Task, nid: int, cid: int, hazard: Any) -> Applied:
    _delete_own(conn, "notification_hazards", nid, task.name)
    if not hazard:
        return Applied()
    conn.execute(
        "INSERT INTO notification_hazards (notification_id, position, hazard_name,"
        " hazard_category_id, is_primary, provenance, ai_classification_id)"
        " VALUES (%s, 1, %s, NULL, NULL, 'ai', %s)",
        (nid, str(hazard), cid),
    )
    return Applied(written=1)


def _origin_country(conn: Connection, task: Task, nid: int, cid: int, country: Any) -> Applied:
    _delete_own(conn, "notification_countries", nid, task.name)
    if country is None or country == "unknown":
        return Applied()
    row = conn.execute(
        "INSERT INTO notification_countries (notification_id, country_iso2, role, provenance,"
        " ai_classification_id)"
        " SELECT %s, iso2, 'origin', 'ai', %s FROM countries WHERE iso2 = %s RETURNING id",
        (nid, cid, str(country)),
    ).fetchone()
    return Applied(written=1) if row else Applied(unmapped=1)


def _product_type(conn: Connection, task: Task, nid: int, cid: int, kind: Any) -> Applied:
    row = conn.execute(
        "UPDATE notifications SET product_type = %s, product_type_provenance = 'ai'"
        " WHERE id = %s AND product_type_provenance IN ('pending', 'ai') RETURNING id",
        (str(kind) if kind is not None else T5_ABSTAIN_PRODUCT_TYPE, nid),
    ).fetchone()
    return Applied(written=1) if row else Applied()


# task name -> (key of the answer in the value, writer)
_WRITERS: dict[str, tuple[str, Writer]] = {
    "hazard_category": ("category", _hazard_category),
    "product_category": ("category", _product_category),
    "hazard": ("hazard", _hazard),
    "origin_country": ("country", _origin_country),
    "product_type": ("product_type", _product_type),
}


def apply_current(conn: Connection, task: Task, notification_id: int) -> Applied:
    """Rewrite what `task` derives for the Notification from its current result. Does not
    commit (the caller commits with the classification or the review)."""
    entry = _WRITERS.get(task.name)
    if entry is None:
        return Applied()
    key, writer = entry
    row = conn.execute(_CURRENT, (notification_id, task.name)).fetchone()
    if row is None:
        return Applied()
    value = effective_value(row["value"], row["review_status"], row["reviewed_value"])
    return writer(conn, task, notification_id, int(row["id"]), value.get(key))
