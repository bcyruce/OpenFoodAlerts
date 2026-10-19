"""`ofa classify`: AI classifications of Notifications into ai_classifications (spec §6).

Per task (T1 hazard_category for now):

1. Candidates: Notifications of the task's Sources (NVWA, openFDA) whose Product type is
   food, feed or food contact material (spec §4.2: non-food and `pending` are never
   classified), newest first.
2. Each candidate's model input is built (`Task.build_input`, the eval snapshot) and its
   `input_hash` computed for the current model, prompt version and taxonomy version.
   A candidate is done when a row with that (task, model, prompt_version, input_hash)
   exists for it: a second run calls nothing. A changed text gives a new hash, so it is
   classified again; a new prompt version classifies everything again.
3. input_hash dedupe: when another Notification already has a row with the same hash, its
   result is copied without a call (FDA lists the same recall text for many products);
   inside one run each distinct input is sent once.
4. Writes, committed per Notification so that an interrupted run keeps what it paid for:
   the ai_classifications row (all versions, value, confidence, evidence_span), then the
   Notification's AI primary hazard: earlier T1 AI rows of notification_hazards are
   removed, and a non-abstained category that maps to a RASFF Hazard category gets a new
   row (provenance ai, is_primary true, hazard_name NULL, hazard_category_id, the
   classification's id). See `primary_category` for merged labels and `other`.

Failures: `ItemFailed` (one request failed after the SDK's retries) skips the Notification
(nothing stored, next run retries it); after MAX_CONSECUTIVE_FAILURES in a row the run
stops. `ClassifierUnavailable` (no key, wrong model) stops the run before anything is
stored for that item.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from psycopg.types.json import Jsonb

from openfoodalerts.classify.model import Classifier, ItemFailed, Usage
from openfoodalerts.classify.prompts import Prompt
from openfoodalerts.classify.run import Classification, classify, hash_for
from openfoodalerts.classify.tasks import HazardCategoryTask, Task, Verdict
from openfoodalerts.db.connection import Connection
from openfoodalerts.parse.model import SHOWN_PRODUCT_TYPES
from openfoodalerts.sources.rasff.lookups import normalize_name

MAX_CONSECUTIVE_FAILURES = 3

_CANDIDATES = """
SELECT n.id, s.code AS source, n.title, n.summary_source, n.product_text, n.hazard_text
FROM notifications n JOIN sources s ON s.id = n.source_id
WHERE s.code = ANY(%(sources)s) AND n.product_type = ANY(%(product_types)s)
ORDER BY n.published_at DESC NULLS LAST, n.id DESC
"""

_DONE = """
SELECT notification_id, input_hash FROM ai_classifications
WHERE task = %s AND model = %s AND prompt_version = %s
"""

_REUSABLE = """
SELECT DISTINCT ON (input_hash) input_hash, value, confidence, abstained, evidence_span,
    schema_version, taxonomy_version
FROM ai_classifications
WHERE task = %s AND model = %s AND prompt_version = %s AND input_hash = ANY(%s)
ORDER BY input_hash, created_at DESC, id DESC
"""

_INSERT = """
INSERT INTO ai_classifications (notification_id, task, value, confidence, abstained,
    evidence_span, model, prompt_version, schema_version, taxonomy_version, input_hash)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (notification_id, task, model, prompt_version, input_hash) DO NOTHING
RETURNING id
"""

# Earlier AI hazard rows that came from this task (T3 rows will have their own task).
_DELETE_AI_HAZARDS = """
DELETE FROM notification_hazards h
USING ai_classifications c
WHERE h.notification_id = %s AND h.provenance = 'ai' AND c.id = h.ai_classification_id
  AND c.task = %s
"""

_INSERT_HAZARD = """
INSERT INTO notification_hazards (notification_id, position, hazard_name,
    hazard_category_id, is_primary, provenance, ai_classification_id)
VALUES (%s, 0, NULL, %s, true, 'ai', %s)
"""


@dataclass
class ClassifyRun:
    task: str
    model: str
    prompt_version: str
    dry_run: bool = False
    # in scope
    candidates: int = 0
    # already classified for this model, prompt version and input
    done: int = 0
    # still to do: distinct inputs to send / copied from a row with the same input_hash
    to_call: int = 0
    reused: int = 0
    # results written by calling the model, of them abstained; items that failed
    classified: int = 0
    abstained: int = 0
    failed: int = 0
    # notification_hazards rows written; non-abstained categories without a category id
    hazards_written: int = 0
    unmapped: int = 0
    usage: Usage = field(default_factory=Usage)
    errors: list[str] = field(default_factory=list)

    def as_log(self) -> dict[str, Any]:
        out = {k: v for k, v in self.__dict__.items() if k not in ("usage", "errors")}
        return out | self.usage.as_dict()


@dataclass(frozen=True)
class _Item:
    notification_id: int
    source: str
    snapshot: dict[str, str]
    input_hash: str


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


def _store(
    conn: Connection,
    task: Task,
    item: _Item,
    result: Classification,
    categories: dict[str, int | None],
    run: ClassifyRun,
) -> None:
    v = result.verdict
    row = conn.execute(
        _INSERT,
        (
            item.notification_id,
            result.task,
            Jsonb(v.value),
            v.confidence,
            v.abstained,
            v.evidence_span,
            result.model,
            result.prompt_version,
            result.schema_version,
            result.taxonomy_version,
            result.input_hash,
        ),
    ).fetchone()
    if row is None:  # written concurrently by another run
        conn.commit()
        return
    if v.abstained:
        run.abstained += 1
    conn.execute(_DELETE_AI_HAZARDS, (item.notification_id, task.name))
    if not v.abstained and v.category is not None and isinstance(task, HazardCategoryTask):
        if v.category not in categories:
            categories[v.category] = primary_category(conn, task, v.category)
        category_id = categories[v.category]
        if category_id is None:
            run.unmapped += 1
        else:
            conn.execute(_INSERT_HAZARD, (item.notification_id, category_id, row["id"]))
            run.hazards_written += 1
    conn.commit()


def _copy(stored: dict[str, Any], task: Task, prompt: Prompt, model: str) -> Classification:
    value = stored["value"]
    return Classification(
        task=task.name,
        verdict=Verdict(
            category=None if stored["abstained"] else value.get("category"),
            confidence=stored["confidence"],
            abstained=stored["abstained"],
            evidence_span=stored["evidence_span"],
            abstain_reason=value.get("abstain_reason"),
            value=value,
        ),
        model=model,
        prompt_version=prompt.version,
        schema_version=stored["schema_version"],
        taxonomy_version=stored["taxonomy_version"],
        input_hash=stored["input_hash"],
    )


def classify_notifications(
    conn: Connection,
    *,
    task: Task,
    prompt: Prompt,
    model: str,
    make_classifier: Callable[[], Classifier],
    sources: Sequence[str] | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> ClassifyRun:
    run = ClassifyRun(task.name, model, prompt.version, dry_run=dry_run)
    wanted = [s for s in task.sources if sources is None or s in sources]
    rows = conn.execute(
        _CANDIDATES, {"sources": wanted, "product_types": list(SHOWN_PRODUCT_TYPES)}
    ).fetchall()
    run.candidates = len(rows)
    done = {
        (r["notification_id"], r["input_hash"])
        for r in conn.execute(_DONE, (task.name, model, prompt.version)).fetchall()
    }
    todo: list[_Item] = []
    for r in rows:
        snapshot = task.build_input(r["source"], r)
        item = _Item(r["id"], r["source"], snapshot, hash_for(task, prompt, model, snapshot))
        if (item.notification_id, item.input_hash) in done:
            run.done += 1
        else:
            todo.append(item)
    if limit is not None:
        todo = todo[:limit]
    known: dict[str, Classification] = {
        r["input_hash"]: _copy(r, task, prompt, model)
        for r in conn.execute(
            _REUSABLE, (task.name, model, prompt.version, [i.input_hash for i in todo])
        ).fetchall()
    }
    conn.commit()
    run.to_call = len({i.input_hash for i in todo} - set(known))
    # copied without a call: from an earlier row, or from a twin sent in this run
    run.reused = len(todo) - run.to_call
    if dry_run or not todo:
        return run
    classifier = make_classifier() if run.to_call else None
    if classifier is not None and classifier.model != model:
        raise ValueError(f"classifier {classifier.model!r} is not model {model!r}")
    categories: dict[str, int | None] = {}
    reused = 0
    consecutive_failures = 0
    for item in todo:
        result = known.get(item.input_hash)
        if result is not None:
            reused += 1
        else:
            assert classifier is not None
            try:
                result = classify(
                    task, prompt, classifier, item.source, item.snapshot, usage=run.usage
                )
            except ItemFailed as exc:
                run.failed += 1
                run.errors.append(f"notification {item.notification_id}: {exc}")
                consecutive_failures += 1
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    raise
                continue
            consecutive_failures = 0
            known[item.input_hash] = result
            run.classified += 1
        _store(conn, task, item, result, categories, run)
    run.reused = reused
    return run
