"""`ofa classify`: AI classifications of Notifications into ai_classifications (spec §6).

Per task (T1-T6; `--task all` runs them in `tasks.RUN_ORDER`, T5 first):

1. Candidates: Notifications of the task's Sources (NVWA, openFDA) whose Product type is
   food, feed or food contact material (spec §4.2: non-food and `pending` are never
   classified), newest first. T5 product_type instead takes those the Product type rules
   could not decide (`pending`) and those it decided before (`ai`, so a changed text or a
   new prompt is classified again); what it finds non-food leaves the other tasks' scope.
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
   Notification's derived AI rows of the task are rewritten from its current
   classification's effective value (`effective.rederive`, shared with the review actions
   of ticket 20): T1 the AI primary hazard, T2 the Product category, T3 the Hazard name,
   T4 the origin country, T5 the Product type (see `effective.WRITERS`).

Failures: `ItemFailed` (one request failed after the SDK's retries) skips the Notification
(nothing stored, next run retries it); after MAX_CONSECUTIVE_FAILURES in a row the run
stops. `ClassifierUnavailable` (no key, wrong model) stops the run before anything is
stored for that item.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from psycopg.types.json import Jsonb

from openfoodalerts.classify.effective import Derived, rederive
from openfoodalerts.classify.model import Classifier, ItemFailed, Usage
from openfoodalerts.classify.prompts import Prompt
from openfoodalerts.classify.run import Classification, classify, hash_for
from openfoodalerts.classify.tasks import Task, Verdict
from openfoodalerts.db.connection import Connection
from openfoodalerts.parse.model import SHOWN_PRODUCT_TYPES

MAX_CONSECUTIVE_FAILURES = 3

_CANDIDATES = """
SELECT n.id, s.code AS source, n.title, n.summary_source, n.product_text, n.hazard_text
FROM notifications n JOIN sources s ON s.id = n.source_id
WHERE s.code = ANY(%(sources)s) AND {scope}
ORDER BY n.published_at DESC NULLS LAST, n.id DESC
"""
# T5 runs where the rules could not decide, and again where it decided before.
_T5_SCOPE = "n.product_type_provenance IN ('pending', 'ai')"
_SHOWN_SCOPE = "n.product_type = ANY(%(product_types)s)"

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
    # derived rows written (`effective.rederive`: hazards, Product categories, origin
    # countries, Product types); answers without a row to write (T1 `other`)
    written: int = 0
    unmapped: int = 0
    usage: Usage = field(default_factory=Usage)
    errors: list[str] = field(default_factory=list)

    def as_log(self) -> dict[str, Any]:
        out = {k: v for k, v in self.__dict__.items() if k not in ("usage", "errors")}
        return out | self.usage.as_dict()


@dataclass(frozen=True)
class Item:
    notification_id: int
    source: str
    snapshot: dict[str, str]
    input_hash: str


def store_result(
    conn: Connection,
    task: Task,
    item: Item,
    result: Classification,
    derived: Derived,
    run: ClassifyRun,
) -> bool:
    """Write one result for one Notification, rederive its rows, commit. False when the
    row existed already (idempotent: also used by the Batch backfill, `classify.batch`)."""
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
        return False
    if v.abstained:
        run.abstained += 1
    rederive(conn, task, item.notification_id, derived)
    run.written, run.unmapped = derived.written, derived.unmapped
    conn.commit()
    return True


def copy_result(stored: dict[str, Any], task: Task, prompt: Prompt, model: str) -> Classification:
    value = stored["value"]
    key = getattr(task, "value_key", "category")  # T1: category
    return Classification(
        task=task.name,
        verdict=Verdict(
            category=None if stored["abstained"] else value.get(key),
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


def candidate_rows(
    conn: Connection,
    task: Task,
    sources: Sequence[str] | None = None,
    *,
    ids: Sequence[int] | None = None,
) -> list[dict[str, Any]]:
    """The task's candidates (scope: module docstring), newest first; only `ids` if given."""
    wanted = [s for s in task.sources if sources is None or s in sources]
    scope = _T5_SCOPE if task.name == "product_type" else _SHOWN_SCOPE
    if ids is not None:
        scope += " AND n.id = ANY(%(ids)s)"
    rows: list[dict[str, Any]] = conn.execute(
        _CANDIDATES.format(scope=scope),
        {"sources": wanted, "product_types": list(SHOWN_PRODUCT_TYPES), "ids": list(ids or ())},
    ).fetchall()
    return rows


def plan_items(
    conn: Connection,
    run: ClassifyRun,
    *,
    task: Task,
    prompt: Prompt,
    sources: Sequence[str] | None = None,
) -> list[Item]:
    """The candidates not yet done for this model, prompt version and input, newest first
    (counts `run.candidates` and `run.done`)."""
    rows = candidate_rows(conn, task, sources)
    run.candidates = len(rows)
    done = {
        (r["notification_id"], r["input_hash"])
        for r in conn.execute(_DONE, (task.name, run.model, prompt.version)).fetchall()
    }
    todo: list[Item] = []
    for r in rows:
        snapshot = task.build_input(r["source"], r)
        item = Item(r["id"], r["source"], snapshot, hash_for(task, prompt, run.model, snapshot))
        if (item.notification_id, item.input_hash) in done:
            run.done += 1
        else:
            todo.append(item)
    return todo


def reusable_results(
    conn: Connection, items: Sequence[Item], *, task: Task, prompt: Prompt, model: str
) -> dict[str, Classification]:
    """Stored results with the same input_hash, to copy instead of calling the model."""
    return {
        r["input_hash"]: copy_result(r, task, prompt, model)
        for r in conn.execute(
            _REUSABLE, (task.name, model, prompt.version, [i.input_hash for i in items])
        ).fetchall()
    }


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
    todo = plan_items(conn, run, task=task, prompt=prompt, sources=sources)
    if limit is not None:
        todo = todo[:limit]
    known = reusable_results(conn, todo, task=task, prompt=prompt, model=model)
    conn.commit()
    run.to_call = len({i.input_hash for i in todo} - set(known))
    # copied without a call: from an earlier row, or from a twin sent in this run
    run.reused = len(todo) - run.to_call
    if dry_run or not todo:
        return run
    classifier = make_classifier() if run.to_call else None
    if classifier is not None and classifier.model != model:
        raise ValueError(f"classifier {classifier.model!r} is not model {model!r}")
    derived = Derived()
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
        store_result(conn, task, item, result, derived, run)
    run.reused = reused
    return run
