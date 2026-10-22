"""The Anthropic Message Batches and OpenAI Batch backends of `ofa classify --batch`,
against stand-in SDK clients (no network)."""

import json
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import openai
import pytest
from anthropic.types import Message

from openfoodalerts.classify.anthropic_model import AnthropicBatches, AnthropicClassifier
from openfoodalerts.classify.batch import BatchRequest
from openfoodalerts.classify.model import ClassifierUnavailable, ItemFailed, ModelRequest, Usage
from openfoodalerts.classify.openai_model import OpenAIBatches, OpenAIClassifier

REQUEST = ModelRequest(
    task="hazard_category",
    source="openfda",
    snapshot={"reason_for_recall": "Listeria"},
    system="FIXED SYSTEM PROMPT\n",
    user='{"source": "openfda", "input": {"reason_for_recall": "Listeria"}}',
    output_schema={"type": "object", "properties": {}, "additionalProperties": False},
)
OUTPUT = {"evidence_span": "Listeria", "category": "allergens", "confidence": "high"}


def message(text: str, stop_reason: str = "end_turn") -> Message:
    return Message.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-haiku-5-5",
            "content": [{"type": "text", "text": text}],
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 50, "output_tokens": 30, "cache_read_input_tokens": 4000},
        }
    )


class AnthropicStandIn:
    """`messages.batches.create / retrieve / results` of the Anthropic SDK."""

    def __init__(self) -> None:
        self.created: list[list[dict[str, Any]]] = []
        self.status = "in_progress"
        self.items: list[Any] = []
        self.error: Exception | None = None
        self.messages = SimpleNamespace(batches=self)

    def create(self, *, requests: list[dict[str, Any]]) -> Any:
        if self.error:
            raise self.error
        self.created.append(requests)
        return SimpleNamespace(id="msgbatch_1", processing_status="in_progress")

    def retrieve(self, batch_id: str) -> Any:
        counts = SimpleNamespace(processing=1, succeeded=2, errored=1, canceled=0, expired=0)
        return SimpleNamespace(id=batch_id, processing_status=self.status, request_counts=counts)

    def results(self, batch_id: str) -> list[Any]:
        return self.items


def anthropic_result(custom_id: str, result: dict[str, Any]) -> Any:
    return SimpleNamespace(custom_id=custom_id, result=SimpleNamespace(**result))


def test_anthropic_batch_requests_are_the_synchronous_requests() -> None:
    client = AnthropicStandIn()
    classifier = AnthropicClassifier(client=client)
    backend = AnthropicBatches(classifier)
    assert (backend.provider, backend.model) == ("anthropic", "claude-haiku-5-5")
    params = backend.params(REQUEST)
    assert params == classifier.request_params(REQUEST)
    assert backend.submit([BatchRequest("ofa-1-0", params)]) == "msgbatch_1"
    assert client.created == [[{"custom_id": "ofa-1-0", "params": params}]]


def test_anthropic_status_and_results_are_parsed_like_a_synchronous_answer() -> None:
    client = AnthropicStandIn()
    backend = AnthropicBatches(AnthropicClassifier(client=client))
    status = backend.status("msgbatch_1")
    assert not status.ended
    assert "processing 1" in status.progress and "errored 1" in status.progress
    client.status = "ended"
    assert backend.status("msgbatch_1").ended
    error = SimpleNamespace(error=SimpleNamespace(type="overloaded_error", message="Overloaded"))
    client.items = [
        anthropic_result("a", {"type": "succeeded", "message": message(json.dumps(OUTPUT))}),
        anthropic_result("b", {"type": "succeeded", "message": message("", "refusal")}),
        anthropic_result("c", {"type": "errored", "error": error}),
        anthropic_result("d", {"type": "expired"}),
        anthropic_result("e", {"type": "canceled"}),
    ]
    a, b, c, d, e = backend.results("msgbatch_1")
    assert a.custom_id == "a" and a.response is not None
    assert a.response.output == OUTPUT
    assert a.response.usage == Usage(0, 50, 30, 0, 4000)
    assert b.response is not None and b.response.failure == "refusal"
    assert (c.response, c.error) == (None, "errored: overloaded_error: Overloaded")
    assert (d.error, e.error) == ("expired", "canceled")


def test_anthropic_submission_errors_say_whether_to_stop() -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages/batches")
    client = AnthropicStandIn()
    backend = AnthropicBatches(AnthropicClassifier(client=client))
    client.error = anthropic.AuthenticationError(
        "no", response=httpx2.Response(401, request=request), body=None
    )
    with pytest.raises(ClassifierUnavailable):
        backend.submit([BatchRequest("ofa-1-0", {})])
    client.error = anthropic.InternalServerError(
        "no", response=httpx2.Response(500, request=request), body=None
    )
    with pytest.raises(ItemFailed):
        backend.submit([BatchRequest("ofa-1-0", {})])


class OpenAIStandIn:
    """`files.create / content` and `batches.create / retrieve` of the OpenAI SDK."""

    def __init__(self) -> None:
        self.uploads: list[tuple[str, bytes, str]] = []
        self.batches_created: list[dict[str, Any]] = []
        self.status = "in_progress"
        self.contents: dict[str, str] = {}
        self.output_file_id: str | None = None
        self.error_file_id: str | None = None
        self.files = SimpleNamespace(create=self._upload, content=self._content)
        self.batches = SimpleNamespace(create=self._create, retrieve=self._retrieve)

    def _upload(self, *, file: tuple[str, bytes], purpose: str) -> Any:
        self.uploads.append((file[0], file[1], purpose))
        return SimpleNamespace(id="file-in")

    def _content(self, file_id: str) -> Any:
        return SimpleNamespace(text=self.contents[file_id])

    def _create(self, **kw: Any) -> Any:
        self.batches_created.append(kw)
        return SimpleNamespace(id="batch_1")

    def _retrieve(self, batch_id: str) -> Any:
        return SimpleNamespace(
            id=batch_id,
            status=self.status,
            request_counts=SimpleNamespace(total=4, completed=2, failed=1),
            output_file_id=self.output_file_id,
            error_file_id=self.error_file_id,
        )


def response_body(text: str) -> dict[str, Any]:
    return {
        "id": "resp_1",
        "status": "completed",
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": text}]},
        ],
        "usage": {
            "input_tokens": 4050,
            "input_tokens_details": {"cached_tokens": 4000},
            "output_tokens": 90,
        },
    }


def test_openai_batch_uploads_one_responses_line_per_request() -> None:
    client = OpenAIStandIn()
    classifier = OpenAIClassifier(client=client)
    backend = OpenAIBatches(classifier)
    assert (backend.provider, backend.model) == ("openai", "gpt-5-mini")
    params = backend.params(REQUEST)
    assert params == classifier.request_params(REQUEST)
    assert backend.submit([BatchRequest("ofa-1-0", params), BatchRequest("ofa-1-1", params)]) == (
        "batch_1"
    )
    [(name, data, purpose)] = client.uploads
    assert purpose == "batch" and name.endswith(".jsonl")
    lines = [json.loads(line) for line in data.decode().splitlines()]
    assert lines == [
        {"custom_id": "ofa-1-0", "method": "POST", "url": "/v1/responses", "body": params},
        {"custom_id": "ofa-1-1", "method": "POST", "url": "/v1/responses", "body": params},
    ]
    [created] = client.batches_created
    assert created["input_file_id"] == "file-in"
    assert (created["endpoint"], created["completion_window"]) == ("/v1/responses", "24h")


def test_openai_status_and_results_from_the_output_and_error_files() -> None:
    client = OpenAIStandIn()
    backend = OpenAIBatches(OpenAIClassifier(client=client))
    status = backend.status("batch_1")
    assert not status.ended and "in_progress" in status.progress
    for ended in ("completed", "failed", "expired", "cancelled"):
        client.status = ended
        assert backend.status("batch_1").ended
    client.output_file_id, client.error_file_id = "file-out", "file-err"
    ok = {"status_code": 200, "request_id": "r", "body": response_body(json.dumps(OUTPUT))}
    failed = {"status_code": 200, "body": {"id": "resp_2", "status": "failed", "error": {}}}
    bad = {"status_code": 400, "body": {"error": {"message": "Invalid schema"}}}
    client.contents = {
        "file-out": "\n".join(
            json.dumps({"id": f"l{n}", "custom_id": c, "response": r, "error": None})
            for n, (c, r) in enumerate([("a", ok), ("b", failed), ("c", bad)])
        )
        + "\n",
        "file-err": json.dumps(
            {
                "id": "l3",
                "custom_id": "d",
                "response": None,
                "error": {"code": "batch_expired", "message": "expired"},
            }
        ),
    }
    a, b, c, d = backend.results("batch_1")
    assert a.response is not None and a.response.output == OUTPUT
    assert a.response.usage == Usage(0, 50, 90, 0, 4000)
    assert b.response is None and "failed" in (b.error or "")
    assert c.response is None and c.error == "HTTP 400: Invalid schema"
    assert d.response is None and d.error == "error: batch_expired: expired"


def test_openai_without_result_files_yields_nothing() -> None:
    client = OpenAIStandIn()
    client.status = "expired"
    assert list(OpenAIBatches(OpenAIClassifier(client=client)).results("batch_1")) == []


def test_openai_submission_errors_say_whether_to_stop() -> None:
    request = httpx2.Request("POST", "https://api.openai.com/v1/files")
    client = OpenAIStandIn()

    def refuse(**kw: Any) -> Any:
        raise openai.PermissionDeniedError(
            "no", response=httpx2.Response(403, request=request), body=None
        )

    client.files = SimpleNamespace(create=refuse, content=None)
    with pytest.raises(ClassifierUnavailable):
        OpenAIBatches(OpenAIClassifier(client=client)).submit([BatchRequest("ofa-1-0", {})])


def test_the_registry_builds_batch_backends(monkeypatch: pytest.MonkeyPatch) -> None:
    from openfoodalerts.classify.registry import make_batch_backend
    from openfoodalerts.eval.labelset import default_taxonomy_path, load_taxonomy

    taxonomy = load_taxonomy(default_taxonomy_path())
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    for model, key in (("gpt-5-mini", "OPENAI_API_KEY"), ("claude-haiku-5-5", "ANTHROPIC_API_KEY")):
        with pytest.raises(ClassifierUnavailable, match=key):
            make_batch_backend(model, taxonomy)
        monkeypatch.setenv(key, "sk-test")
        assert make_batch_backend(model, taxonomy).model == model
    assert make_batch_backend("fake", taxonomy).provider == "fake"
