"""`ofa classify --batch`: submit, persist, resume and store a Batch backfill, against the
test database with a stand-in Batch backend (the fake model's answers, no network)."""

import json
from collections.abc import Iterable, Iterator, Sequence
from datetime import UTC, datetime
from typing import Any

import pytest

from openfoodalerts.classify.batch import (
    BatchRequest,
    BatchResult,
    BatchStatus,
    collect_batches,
    submit_batches,
)
from openfoodalerts.classify.fake import KeywordClassifier
from openfoodalerts.classify.model import ModelRequest, ModelResponse, Usage
from openfoodalerts.classify.prompts import load_prompt
from openfoodalerts.classify.run import hash_for
from openfoodalerts.classify.tasks import HazardCategoryTask
from openfoodalerts.db.connection import Connection
from openfoodalerts.eval.labelset import default_taxonomy_path, load_taxonomy
from tests.mail_data import add_notification

pytestmark = pytest.mark.db

T = datetime(2026, 10, 24, 8, 0, tzinfo=UTC)
TAXONOMY = load_taxonomy(default_taxonomy_path())
TASK = HazardCategoryTask(TAXONOMY)
PROMPT = load_prompt(TASK.name)
ALLERGENS = 21798


class Backend:
    """A Batch provider in memory: answers with the fake model once `end()` is called;
    `errors` / `missing` make chosen requests error or come back without a result."""

    provider = "fake"
    model = "fake"

    def __init__(self) -> None:
        self.batches: dict[str, list[BatchRequest]] = {}
        self.ended: set[str] = set()
        self.errors: set[str] = set()  # substrings of the user message
        self.missing: set[str] = set()
        self.fail_submit: Exception | None = None
        self.break_after: int | None = None  # results iterator dies after this many
        self.fake = KeywordClassifier(TAXONOMY)

    def params(self, request: ModelRequest) -> dict[str, Any]:
        return {
            "task": request.task,
            "source": request.source,
            "snapshot": dict(request.snapshot),
            "system": request.system,
            "user": request.user,
            "output_schema": request.output_schema,
        }

    def submit(self, requests: Sequence[BatchRequest]) -> str:
        if self.fail_submit is not None:
            raise self.fail_submit
        batch_id = f"fb_{len(self.batches) + 1}"
        self.batches[batch_id] = list(requests)
        return batch_id

    def status(self, batch_id: str) -> BatchStatus:
        done = batch_id in self.ended
        return BatchStatus(ended=done, progress="ended" if done else "in_progress")

    def end(self) -> None:
        self.ended |= set(self.batches)

    def results(self, batch_id: str) -> Iterable[BatchResult]:
        return self._results(batch_id)

    def _results(self, batch_id: str) -> Iterator[BatchResult]:
        for n, r in enumerate(self.batches[batch_id]):
            if self.break_after is not None and n >= self.break_after:
                raise ConnectionError("results download interrupted")
            user = r.params["user"]
            if any(s in user for s in self.missing):
                continue
            if any(s in user for s in self.errors):
                yield BatchResult(r.custom_id, None, "errored: overloaded_error")
                continue
            answer = self.fake.complete(ModelRequest(**r.params))
            usage = Usage(input_tokens=100, output_tokens=20, cache_read_input_tokens=4000)
            yield BatchResult(r.custom_id, ModelResponse(answer.output, answer.failure, usage))


def fda(db: Connection, key: str, reason: str, product: str = "Cookies") -> int:
    nid = add_notification(db, "openfda", key, first_seen_at=T, hazard_text=reason)
    db.execute("UPDATE notifications SET product_text = %s WHERE id = %s", (product, nid))
    return nid


def submit(db: Connection, backend: Backend, **kw: Any) -> Any:
    return submit_batches(
        db, task=TASK, prompt=PROMPT, model="fake", make_backend=lambda: backend, **kw
    )


def collect(db: Connection, backend: Backend) -> Any:
    return collect_batches(db, make_backend=lambda model: backend, taxonomy=TAXONOMY)


def rows(db: Connection, sql: str, *params: object) -> list[dict[str, Any]]:
    return db.execute(sql, params).fetchall()


def test_one_request_per_distinct_input_is_submitted_and_remembered(db: Connection) -> None:
    a = fda(db, "F-1", "Undeclared peanut.")
    twin = fda(db, "F-2", "Undeclared peanut.")  # same text: one request for both
    b = fda(db, "F-3", "Listeria monocytogenes.")
    db.commit()
    backend = Backend()
    result = submit(db, backend)
    assert (result.candidates, result.requests, result.reused, result.waiting) == (3, 2, 0, 0)
    [(provider_id, sent)] = backend.batches.items()
    assert len(sent) == 2
    [batch] = rows(db, "SELECT * FROM classify_batches")
    assert batch["provider_batch_id"] == provider_id
    assert (batch["status"], batch["provider"], batch["task"]) == ("submitted", "fake", TASK.name)
    assert (batch["model"], batch["prompt_version"], batch["request_count"]) == ("fake", "v1", 2)
    assert batch["submitted_at"] is not None
    requests = rows(
        db,
        "SELECT custom_id, input_hash, source, notification_ids, status"
        " FROM classify_batch_requests ORDER BY custom_id",
    )
    peanut = hash_for(
        TASK,
        PROMPT,
        "fake",
        {"product_description": "Cookies", "reason_for_recall": "Undeclared peanut."},
    )
    by_hash = {r["input_hash"]: r for r in requests}
    assert sorted(by_hash[peanut]["notification_ids"]) == sorted([a, twin])
    assert {r["status"] for r in requests} == {"pending"}
    assert {r["custom_id"] for r in requests} == {s.custom_id for s in sent}
    # what was sent is the request of `ofa classify` (prompt, rendered input, schema)
    assert all(s.params["system"] == PROMPT.system for s in sent)
    assert any(
        json.loads(s.params["user"])["input"]["reason_for_recall"] == "Listeria monocytogenes."
        for s in sent
    )
    assert b in [n for r in requests for n in r["notification_ids"]]
    # nothing is stored before the results are in
    assert rows(db, "SELECT * FROM ai_classifications") == []


def test_inputs_waiting_in_an_open_batch_are_not_sent_again(db: Connection) -> None:
    fda(db, "F-1", "Undeclared peanut.")
    db.commit()
    backend = Backend()
    submit(db, backend)
    again = submit(db, backend)
    assert (again.requests, again.waiting) == (0, 1)
    assert len(backend.batches) == 1


def test_results_are_stored_through_the_same_path_as_ofa_classify(db: Connection) -> None:
    a = fda(db, "F-1", "Undeclared peanut.")
    twin = fda(db, "F-2", "Undeclared peanut.")
    fda(db, "F-3", "Listeria monocytogenes.")
    db.commit()
    backend = Backend()
    submit(db, backend)
    [waiting] = collect(db, backend)
    assert (waiting.status, waiting.stored) == ("submitted", 0)
    assert rows(db, "SELECT * FROM ai_classifications") == []
    backend.end()
    [done] = collect(db, backend)
    assert (done.status, done.stored, done.failed) == ("stored", 3, 0)
    assert done.usage == Usage(2, 200, 40, 0, 8000)
    stored = rows(
        db,
        "SELECT notification_id, value, model, prompt_version, input_hash"
        " FROM ai_classifications ORDER BY notification_id",
    )
    assert len(stored) == 3
    assert {r["model"] for r in stored} == {"fake"}
    assert stored[0]["notification_id"] == a and stored[0]["value"] == {"category": "allergens"}
    # derived rows via effective.rederive, as in sync classify
    hazards = rows(
        db,
        "SELECT h.notification_id, c.rasff_id FROM notification_hazards h"
        " JOIN hazard_categories c ON c.id = h.hazard_category_id WHERE h.provenance = 'ai'"
        " ORDER BY h.notification_id",
    )
    assert [(h["notification_id"], h["rasff_id"]) for h in hazards[:2]] == [
        (a, ALLERGENS),
        (twin, ALLERGENS),
    ]
    [batch] = rows(db, "SELECT status, stored_at, usage FROM classify_batches")
    assert batch["status"] == "stored" and batch["stored_at"] is not None
    assert batch["usage"]["requests"] == 2
    assert {r["status"] for r in rows(db, "SELECT status FROM classify_batch_requests")} == {
        "stored"
    }
    # done: nothing left to submit; collecting again does nothing
    assert submit(db, backend).requests == 0
    assert collect(db, backend) == []


def test_failed_and_missing_requests_are_retried_by_the_next_submission(db: Connection) -> None:
    fda(db, "F-1", "Undeclared peanut.")
    fda(db, "F-2", "Listeria monocytogenes.")
    fda(db, "F-3", "Salmonella.")
    db.commit()
    backend = Backend()
    backend.errors, backend.missing = {"Listeria"}, {"Salmonella"}
    submit(db, backend)
    backend.end()
    [done] = collect(db, backend)
    assert (done.status, done.stored, done.failed) == ("stored", 1, 2)
    failed = rows(
        db, "SELECT error FROM classify_batch_requests WHERE status = 'failed' ORDER BY error"
    )
    assert [f["error"] for f in failed] == [
        "errored: overloaded_error",
        "no result (expired or cancelled)",
    ]
    backend.errors, backend.missing = set(), set()
    retry = submit(db, backend)
    assert (retry.requests, retry.done, retry.waiting) == (2, 1, 0)
    backend.end()
    collect(db, backend)
    assert len(rows(db, "SELECT * FROM ai_classifications")) == 3


def test_an_interrupted_collection_resumes_without_duplicates(db: Connection) -> None:
    for n in range(4):
        fda(db, f"F-{n}", f"Undeclared peanut {n}.")
    db.commit()
    backend = Backend()
    submit(db, backend)
    backend.end()
    backend.break_after = 2
    with pytest.raises(ConnectionError):
        collect(db, backend)
    assert len(rows(db, "SELECT * FROM ai_classifications")) == 2
    [batch] = rows(db, "SELECT status FROM classify_batches")
    assert batch["status"] == "ended"
    backend.break_after = None
    [done] = collect(db, backend)
    assert (done.status, done.stored) == ("stored", 2)
    assert len(rows(db, "SELECT * FROM ai_classifications")) == 4


def test_a_text_that_changed_since_submission_is_not_stored(db: Connection) -> None:
    nid = fda(db, "F-1", "Undeclared peanut.")
    db.commit()
    backend = Backend()
    submit(db, backend)
    db.execute("UPDATE notifications SET hazard_text = 'Undeclared milk.' WHERE id = %s", (nid,))
    db.commit()
    backend.end()
    [done] = collect(db, backend)
    assert (done.stored, done.stale) == (0, 1)
    assert rows(db, "SELECT * FROM ai_classifications") == []
    # the new text is a new input: submitted next time
    assert submit(db, backend).requests == 1


def test_inputs_with_a_stored_twin_are_copied_now_not_sent(db: Connection) -> None:
    fda(db, "F-1", "Undeclared peanut.")
    db.commit()
    backend = Backend()
    submit(db, backend)
    backend.end()
    collect(db, backend)
    fda(db, "F-2", "Undeclared peanut.")
    db.commit()
    later = submit(db, backend)
    assert (later.requests, later.reused) == (0, 1)
    assert len(rows(db, "SELECT * FROM ai_classifications")) == 2


def test_limit_chunks_and_dry_run(db: Connection) -> None:
    for n in range(5):
        fda(db, f"F-{n}", f"Undeclared peanut {n}.")
    db.commit()
    backend = Backend()
    dry = submit(db, backend, dry_run=True)
    assert (dry.requests, dry.batches) == (5, 1)
    assert backend.batches == {} and rows(db, "SELECT * FROM classify_batches") == []
    result = submit(db, backend, limit=4, max_requests=3)
    assert (result.requests, result.batches) == (4, 2)
    assert [len(r) for r in backend.batches.values()] == [3, 1]
    assert result.bytes > 0


def test_a_failed_submission_is_recorded_and_its_inputs_are_sent_again(db: Connection) -> None:
    fda(db, "F-1", "Undeclared peanut.")
    db.commit()
    backend = Backend()
    backend.fail_submit = RuntimeError("HTTP 500")
    with pytest.raises(RuntimeError):
        submit(db, backend)
    [batch] = rows(db, "SELECT status, error, provider_batch_id FROM classify_batches")
    assert batch["status"] == "failed" and "HTTP 500" in batch["error"]
    assert batch["provider_batch_id"] is None
    backend.fail_submit = None
    assert submit(db, backend).requests == 1


def test_a_batch_left_preparing_by_a_crash_is_closed_on_collection(db: Connection) -> None:
    fda(db, "F-1", "Undeclared peanut.")
    db.commit()
    db.execute(
        "INSERT INTO classify_batches (provider, task, model, prompt_version, request_count)"
        " VALUES ('fake', %s, 'fake', 'v1', 1)",
        (TASK.name,),
    )
    db.commit()
    backend = Backend()
    [closed] = collect(db, backend)
    assert closed.status == "failed"
    [batch] = rows(db, "SELECT status, error FROM classify_batches")
    assert batch["status"] == "failed" and "interrupted" in batch["error"]
    assert submit(db, backend).requests == 1
