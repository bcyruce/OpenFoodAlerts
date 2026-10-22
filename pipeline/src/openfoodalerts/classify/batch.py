"""`ofa classify --batch`: the backfill through a provider's Batch API (spec §6.3), at half
price, resumable (ticket 21).

Submission (`submit_batches`), per task, model and prompt version:

1. The candidates and what is done come from the synchronous job (`job.plan_items`), so
   the scope, the inputs and their `input_hash` are exactly those of `ofa classify`.
2. Inputs that already wait in an open batch of the same task, model and prompt version
   are skipped (`waiting`): submitting twice never pays twice. Inputs with a stored twin
   (same input_hash) are copied right away, without a request (`reused`), as in sync.
3. Each remaining distinct input becomes one request (custom_id `ofa-{batch}-{n}`), built
   by `run.make_request` and turned into the provider's parameters by the backend (the
   same parameters as a synchronous call). Requests are split into batches of at most
   `max_requests` and `max_bytes` (well below the providers' limits: Anthropic 100,000
   requests / 256 MB, OpenAI 50,000 / 200 MB; the prompt prefix is repeated in every
   request, about 10-15 kB each).
4. Before anything is sent, the batch and its requests (custom_id <-> input_hash <->
   Notifications) are committed with status `preparing`; then the provider's id is
   recorded (`submitted`). A submission error marks the batch `failed` (its inputs are
   submitted again next time) and is raised.

Collection (`collect_batches`, `ofa classify-batch-status`, also run first by every
`ofa classify --batch`): for each open batch, ask the provider; when it has ended, read
the results and store each one through the synchronous path (`run.checked` = Task.check
+ versions, then `job.store_result` = ai_classifications row + `effective.rederive`).
Before storing, each Notification's current input is rebuilt and its hash compared: a
text that changed since submission is not stored (`stale`; the new text is a new input).
Errored, expired, cancelled or missing results mark the request `failed`: nothing is
stored, and the next submission sends that input again. Storing is idempotent
(`ON CONFLICT DO NOTHING`, per-request status), so an interrupted collection simply
resumes. A batch left `preparing` by a crash (written, never confirmed) is closed as
`failed`; if the provider did receive it, its results are never read (at worst those
inputs are paid twice).
"""

import json
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from psycopg.types.json import Jsonb

from openfoodalerts.classify.effective import Derived
from openfoodalerts.classify.job import (
    ClassifyRun,
    Item,
    candidate_rows,
    plan_items,
    reusable_results,
    store_result,
)
from openfoodalerts.classify.model import ModelRequest, ModelResponse, Usage
from openfoodalerts.classify.prompts import Prompt, load_prompt
from openfoodalerts.classify.run import checked, hash_for, make_request
from openfoodalerts.classify.tasks import Task, make_task
from openfoodalerts.db.connection import Connection
from openfoodalerts.eval.labelset import Taxonomy

MAX_REQUESTS = 10_000
MAX_BYTES = 100_000_000
OPEN = ("preparing", "submitted", "ended")
NO_RESULT = "no result (expired or cancelled)"
INTERRUPTED = (
    "interrupted before the provider confirmed the submission; if the provider's console"
    " shows a batch created at that time, cancel it (its results are not read)"
)


@dataclass(frozen=True)
class BatchRequest:
    custom_id: str
    # the provider's request parameters (Anthropic `params`, OpenAI `body`)
    params: dict[str, Any]


@dataclass(frozen=True)
class BatchStatus:
    ended: bool
    # the provider's progress in its own words, e.g. "processing 12, succeeded 88"
    progress: str


@dataclass(frozen=True)
class BatchResult:
    custom_id: str
    # the parsed answer (as a synchronous call returns it); None when the request failed
    response: ModelResponse | None
    error: str | None = None


class BatchBackend(Protocol):
    """One provider's Batch API for one model (`anthropic_model.AnthropicBatches`,
    `openai_model.OpenAIBatches`, `fake_batch.FakeBatches`)."""

    @property
    def provider(self) -> str: ...
    @property
    def model(self) -> str: ...

    def params(self, request: ModelRequest) -> dict[str, Any]: ...
    def submit(self, requests: Sequence[BatchRequest]) -> str: ...
    def status(self, batch_id: str) -> BatchStatus: ...
    def results(self, batch_id: str) -> Iterable[BatchResult]: ...


@dataclass
class BatchSubmission:
    task: str
    model: str
    prompt_version: str
    dry_run: bool = False
    candidates: int = 0
    done: int = 0
    # inputs already in an open batch; copied from a stored twin; requests submitted
    waiting: int = 0
    reused: int = 0
    requests: int = 0
    # batches submitted (or that would be), their size in bytes of request parameters
    batches: int = 0
    bytes: int = 0
    batch_ids: list[int] = field(default_factory=list)

    def as_log(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if k != "batch_ids"}


@dataclass
class BatchCollection:
    batch_id: int
    provider_batch_id: str | None
    task: str
    model: str
    prompt_version: str
    # the batch's status after this collection
    status: str
    progress: str | None = None
    # Notifications that got a stored result (incl. abstains); requests that failed;
    # Notifications whose text changed since submission
    stored: int = 0
    abstained: int = 0
    failed: int = 0
    stale: int = 0
    written: int = 0
    unmapped: int = 0
    usage: Usage = field(default_factory=Usage)


_OPEN_HASHES = """
SELECT DISTINCT r.input_hash FROM classify_batch_requests r
JOIN classify_batches b ON b.id = r.batch_id
WHERE b.task = %s AND b.model = %s AND b.prompt_version = %s AND b.status = ANY(%s)
  AND r.status = 'pending'
"""


def _chunks(requests: list[BatchRequest], max_requests: int, max_bytes: int) -> list[list[Any]]:
    chunks: list[list[Any]] = []
    size = 0
    for request in requests:
        n = len(json.dumps(request.params, ensure_ascii=False).encode())
        if not chunks or len(chunks[-1]) >= max_requests or size + n > max_bytes:
            chunks.append([])
            size = 0
        chunks[-1].append(request)
        size += n
    return chunks


def submit_batches(
    conn: Connection,
    *,
    task: Task,
    prompt: Prompt,
    model: str,
    make_backend: Callable[[], BatchBackend],
    sources: Sequence[str] | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    max_requests: int = MAX_REQUESTS,
    max_bytes: int = MAX_BYTES,
) -> BatchSubmission:
    """Submit the task's not-yet-classified inputs as Batches (module docstring)."""
    result = BatchSubmission(task.name, model, prompt.version, dry_run=dry_run)
    run = ClassifyRun(task.name, model, prompt.version, dry_run=dry_run)
    todo = plan_items(conn, run, task=task, prompt=prompt, sources=sources)
    result.candidates, result.done = run.candidates, run.done
    open_hashes = {
        r["input_hash"]
        for r in conn.execute(_OPEN_HASHES, (task.name, model, prompt.version, list(OPEN)))
    }
    waiting = [i for i in todo if i.input_hash in open_hashes]
    todo = [i for i in todo if i.input_hash not in open_hashes]
    result.waiting = len(waiting)
    if limit is not None:
        todo = todo[:limit]
    known = reusable_results(conn, todo, task=task, prompt=prompt, model=model)
    conn.commit()
    copies = [i for i in todo if i.input_hash in known]
    groups: dict[str, list[Item]] = {}
    for item in todo:
        if item.input_hash not in known:
            groups.setdefault(item.input_hash, []).append(item)
    result.reused = len(copies)
    result.requests = len(groups)
    if not dry_run:
        derived = Derived()
        for item in copies:
            store_result(conn, task, item, known[item.input_hash], derived, run)
    if not groups:
        return result
    backend = None if dry_run else make_backend()
    if backend is not None and backend.model != model:
        raise ValueError(f"backend {backend.model!r} is not model {model!r}")
    pending = [
        (
            items,
            make_request(task, prompt, items[0].source, items[0].snapshot),
        )
        for items in groups.values()
    ]
    # custom ids are numbered after the batch row exists; size them with a placeholder
    sized = [
        BatchRequest("", backend.params(r) if backend else _params_for_size(r)) for _, r in pending
    ]
    chunks = _chunks(sized, max_requests, max_bytes)
    result.batches = len(chunks)
    result.bytes = sum(len(json.dumps(s.params, ensure_ascii=False).encode()) for s in sized)
    if backend is None:
        return result
    start = 0
    for chunk in chunks:
        part = pending[start : start + len(chunk)]
        params = [s.params for s in sized[start : start + len(chunk)]]
        start += len(chunk)
        result.batch_ids.append(_submit_one(conn, backend, task, prompt, model, part, params))
    return result


def _params_for_size(request: ModelRequest) -> dict[str, Any]:
    """A provider-neutral stand-in for a request's parameters (dry run: no backend)."""
    return {"system": request.system, "user": request.user, "schema": request.output_schema}


def _submit_one(
    conn: Connection,
    backend: BatchBackend,
    task: Task,
    prompt: Prompt,
    model: str,
    part: list[tuple[list[Item], ModelRequest]],
    params: list[dict[str, Any]],
) -> int:
    row = conn.execute(
        "INSERT INTO classify_batches (provider, task, model, prompt_version, request_count)"
        " VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (backend.provider, task.name, model, prompt.version, len(part)),
    ).fetchone()
    assert row is not None
    batch_id: int = row["id"]
    requests = []
    for n, ((items, _), p) in enumerate(zip(part, params, strict=True)):
        custom_id = f"ofa-{batch_id}-{n}"
        requests.append(BatchRequest(custom_id, p))
        conn.execute(
            "INSERT INTO classify_batch_requests (batch_id, custom_id, input_hash, source,"
            " notification_ids) VALUES (%s, %s, %s, %s, %s)",
            (
                batch_id,
                custom_id,
                items[0].input_hash,
                items[0].source,
                [i.notification_id for i in items],
            ),
        )
    conn.commit()
    try:
        provider_id = backend.submit(requests)
    except Exception as exc:
        conn.rollback()
        conn.execute(
            "UPDATE classify_batches SET status = 'failed', error = %s WHERE id = %s",
            (f"submission failed: {type(exc).__name__}: {exc}", batch_id),
        )
        conn.commit()
        raise
    conn.execute(
        "UPDATE classify_batches SET status = 'submitted', provider_batch_id = %s,"
        " submitted_at = now() WHERE id = %s",
        (provider_id, batch_id),
    )
    conn.commit()
    return batch_id


def collect_batches(
    conn: Connection,
    *,
    make_backend: Callable[[str], BatchBackend],
    taxonomy: Taxonomy,
    task: str | None = None,
    model: str | None = None,
) -> list[BatchCollection]:
    """Poll every open batch (optionally of one task / model) and store the results of
    those that have ended (module docstring). One BatchCollection per open batch."""
    batches = conn.execute(
        "SELECT * FROM classify_batches WHERE status = ANY(%s)"
        " AND (%s::text IS NULL OR task = %s) AND (%s::text IS NULL OR model = %s)"
        " ORDER BY id",
        (list(OPEN), task, task, model, model),
    ).fetchall()
    conn.commit()
    backends: dict[str, BatchBackend] = {}
    out = []
    for batch in batches:
        info = BatchCollection(
            batch["id"],
            batch["provider_batch_id"],
            batch["task"],
            batch["model"],
            batch["prompt_version"],
            batch["status"],
        )
        out.append(info)
        if batch["status"] == "preparing":
            conn.execute(
                "UPDATE classify_batches SET status = 'failed', error = %s WHERE id = %s",
                (INTERRUPTED, batch["id"]),
            )
            conn.commit()
            info.status = "failed"
            continue
        if batch["model"] not in backends:
            backends[batch["model"]] = make_backend(batch["model"])
        backend = backends[batch["model"]]
        if batch["status"] == "submitted":
            status = backend.status(batch["provider_batch_id"])
            info.progress = status.progress
            if not status.ended:
                conn.execute(
                    "UPDATE classify_batches SET progress = %s WHERE id = %s",
                    (status.progress, batch["id"]),
                )
                conn.commit()
                continue
            conn.execute(
                "UPDATE classify_batches SET status = 'ended', progress = %s, ended_at = now()"
                " WHERE id = %s",
                (status.progress, batch["id"]),
            )
            conn.commit()
            info.status = "ended"
        _store_batch(conn, backend, batch, info, taxonomy)
    return out


def _store_batch(
    conn: Connection,
    backend: BatchBackend,
    batch: dict[str, Any],
    info: BatchCollection,
    taxonomy: Taxonomy,
) -> None:
    task = make_task(batch["task"], taxonomy)
    prompt = load_prompt(batch["task"], batch["prompt_version"])
    pending = {
        r["custom_id"]: r
        for r in conn.execute(
            "SELECT * FROM classify_batch_requests WHERE batch_id = %s AND status = 'pending'",
            (batch["id"],),
        )
    }
    conn.commit()
    run = ClassifyRun(task.name, batch["model"], prompt.version)
    derived = Derived()
    usage = Usage(**batch["usage"]) if batch["usage"] else Usage()
    for result in backend.results(batch["provider_batch_id"]):
        request = pending.pop(result.custom_id, None)
        if request is None:  # stored before an interruption, or not ours
            continue
        if result.response is None:
            _mark(conn, batch["id"], result.custom_id, "failed", result.error or "failed")
            info.failed += 1
            continue
        usage.add(result.response.usage)
        usage.requests += 1
        _store_request(
            conn, task, prompt, batch["model"], request, result.response, derived, run, info
        )
        conn.execute(
            "UPDATE classify_batches SET usage = %s WHERE id = %s",
            (Jsonb(usage.as_dict()), batch["id"]),
        )
        _mark(conn, batch["id"], result.custom_id, "stored", None)
    for custom_id in pending:
        _mark(conn, batch["id"], custom_id, "failed", NO_RESULT)
        info.failed += 1
    conn.execute(
        "UPDATE classify_batches SET status = 'stored', stored_at = now(), usage = %s"
        " WHERE id = %s",
        (Jsonb(usage.as_dict()), batch["id"]),
    )
    conn.commit()
    info.status = "stored"
    info.usage = usage
    info.abstained, info.written, info.unmapped = run.abstained, run.written, run.unmapped


def _store_request(
    conn: Connection,
    task: Task,
    prompt: Prompt,
    model: str,
    request: dict[str, Any],
    response: ModelResponse,
    derived: Derived,
    run: ClassifyRun,
    info: BatchCollection,
) -> None:
    ids = list(request["notification_ids"])
    current = {r["id"]: r for r in candidate_rows(conn, task, ids=ids)}
    for nid in ids:
        row = current.get(nid)
        if row is None:  # no longer in the task's scope
            info.stale += 1
            continue
        snapshot = task.build_input(row["source"], row)
        if hash_for(task, prompt, model, snapshot) != request["input_hash"]:
            info.stale += 1
            continue
        item = Item(nid, row["source"], snapshot, request["input_hash"])
        result = checked(task, prompt, model, snapshot, response)
        if store_result(conn, task, item, result, derived, run):
            info.stored += 1


def _mark(conn: Connection, batch_id: int, custom_id: str, status: str, error: str | None) -> None:
    conn.execute(
        "UPDATE classify_batch_requests SET status = %s, error = %s"
        " WHERE batch_id = %s AND custom_id = %s",
        (status, error, batch_id, custom_id),
    )
    conn.commit()
