"""The GPT-5 mini Classifier, against a stand-in SDK client (no network)."""

import json
from typing import Any

import httpx2
import openai
import pytest

from openfoodalerts.classify.model import (
    ClassifierUnavailable,
    ItemFailed,
    ModelRequest,
    Usage,
)
from openfoodalerts.classify.openai_model import (
    GPT_5_MINI,
    OpenAIClassifier,
    parse_response,
    strict_schema,
)

SCHEMA = {
    "type": "object",
    "properties": {
        "evidence_span": {"type": "string"},
        "category": {"type": "string", "enum": ["allergens", "abstain"]},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": ["evidence_span", "category", "confidence"],
    "additionalProperties": False,
}

REQUEST = ModelRequest(
    task="hazard_category",
    source="openfda",
    snapshot={"reason_for_recall": "Listeria"},
    system="FIXED SYSTEM PROMPT\n",
    user='{"source": "openfda", "input": {"reason_for_recall": "Listeria"}}',
    output_schema=SCHEMA,
)

OUTPUT = {
    "evidence_span": "Listeria",
    "category": "pathogenic micro-organisms",
    "confidence": "high",
}


def body(
    content: list[dict[str, Any]] | None = None,
    *,
    status: str = "completed",
    incomplete: str | None = None,
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A Responses API response body (as `Response.model_dump()` and Batch output lines)."""
    return {
        "id": "resp_1",
        "object": "response",
        "status": status,
        "incomplete_details": {"reason": incomplete} if incomplete else None,
        "output": [
            {"type": "reasoning", "id": "rs_1", "summary": []},
            {
                "type": "message",
                "id": "msg_1",
                "role": "assistant",
                "status": "completed",
                "content": content if content is not None else [],
            },
        ],
        "usage": usage,
    }


def text(value: str) -> dict[str, Any]:
    return {"type": "output_text", "text": value, "annotations": []}


class Reply:
    """What `responses.create` returns: something with `model_dump()`."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data

    def model_dump(self) -> dict[str, Any]:
        return self.data


class StandIn:
    """Records `responses.create` calls and answers with queued replies or errors."""

    def __init__(self, *replies: dict[str, Any] | Exception) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []
        self.responses = self

    def create(self, **params: Any) -> Reply:
        self.calls.append(params)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return Reply(reply)


def status_error(cls: type[openai.APIStatusError], code: int) -> openai.APIStatusError:
    request = httpx2.Request("POST", "https://api.openai.com/v1/responses")
    return cls("boom", response=httpx2.Response(code, request=request), body=None)


def test_the_model_is_gpt_5_mini() -> None:
    assert GPT_5_MINI == "gpt-5-mini"
    assert OpenAIClassifier(client=StandIn()).model == "gpt-5-mini"


def test_the_request_puts_the_prompt_first_and_asks_for_strict_json() -> None:
    client = StandIn(body([text(json.dumps(OUTPUT))]))
    OpenAIClassifier(client=client, effort="low").complete(REQUEST)
    [params] = client.calls
    assert params["model"] == "gpt-5-mini"
    # the fixed prompt is the cacheable prefix; the item is the only input
    assert params["instructions"] == "FIXED SYSTEM PROMPT\n"
    assert params["input"] == REQUEST.user
    assert params["text"] == {
        "format": {
            "type": "json_schema",
            "name": "hazard_category",
            "schema": SCHEMA,
            "strict": True,
        }
    }
    assert params["reasoning"] == {"effort": "low"}
    assert params["max_output_tokens"] >= 1024
    # one cache key per task (same prefix), nothing stored at OpenAI, no sampling parameters
    assert params["prompt_cache_key"] == "openfoodalerts-hazard_category"
    assert params["store"] is False
    assert not {"temperature", "top_p"} & set(params)


def test_the_json_answer_and_the_usage_come_back_with_cached_tokens_split_out() -> None:
    reply = body(
        [text(json.dumps(OUTPUT))],
        usage={
            "input_tokens": 3040,
            "input_tokens_details": {"cached_tokens": 3000},
            "output_tokens": 180,
            "output_tokens_details": {"reasoning_tokens": 150},
            "total_tokens": 3220,
        },
    )
    response = OpenAIClassifier(client=StandIn(reply)).complete(REQUEST)
    assert response.output == OUTPUT
    assert response.failure is None
    # uncached input 40, output incl. reasoning 180, no cache write, cache read 3000
    assert response.usage == Usage(0, 40, 180, 0, 3000)
    assert response.request_id == "resp_1"


@pytest.mark.parametrize(
    ("reply", "failure", "output"),
    [
        (body([{"type": "refusal", "refusal": "I can't help with that."}]), "refusal", None),
        (body(status="incomplete", incomplete="content_filter"), "refusal", None),
        (
            body([text('{"evid')], status="incomplete", incomplete="max_output_tokens"),
            "truncated",
            None,
        ),
        (body([text("not json")]), None, "not json"),
        (body([]), "invalid_output", None),
    ],
)
def test_no_usable_answer_says_why(
    reply: dict[str, Any], failure: str | None, output: object
) -> None:
    response = OpenAIClassifier(client=StandIn(reply)).complete(REQUEST)
    assert (response.output, response.failure) == (output, failure)


def test_a_failed_response_fails_the_item() -> None:
    with pytest.raises(ItemFailed, match="server_error"):
        parse_response(body(status="failed") | {"error": {"code": "server_error"}})


def test_errors_that_concern_one_request_fail_the_item_only() -> None:
    for error in (
        status_error(openai.BadRequestError, 400),
        status_error(openai.RateLimitError, 429),
        status_error(openai.InternalServerError, 500),
        openai.APIConnectionError(request=httpx2.Request("POST", "https://x")),
    ):
        with pytest.raises(ItemFailed):
            OpenAIClassifier(client=StandIn(error)).complete(REQUEST)


def test_errors_that_concern_every_request_stop_the_run() -> None:
    for error in (
        status_error(openai.AuthenticationError, 401),
        status_error(openai.PermissionDeniedError, 403),
        status_error(openai.NotFoundError, 404),
    ):
        with pytest.raises(ClassifierUnavailable):
            OpenAIClassifier(client=StandIn(error)).complete(REQUEST)


def test_without_an_api_key_nothing_is_called_and_the_message_says_what_to_set() -> None:
    with pytest.raises(ClassifierUnavailable, match="OPENAI_API_KEY"):
        OpenAIClassifier.from_env(environ={})
    # an Anthropic key is no OpenAI key
    with pytest.raises(ClassifierUnavailable, match="OPENAI_API_KEY"):
        OpenAIClassifier.from_env(environ={"OPENAI_API_KEY": " ", "ANTHROPIC_API_KEY": "sk-ant"})
    with pytest.raises(ClassifierUnavailable, match="from_env"):
        OpenAIClassifier().complete(REQUEST)


def test_with_a_key_a_real_client_is_built_without_calling_anything() -> None:
    classifier = OpenAIClassifier.from_env(
        environ={"OPENAI_API_KEY": "sk-test", "OFA_OPENAI_EFFORT": "minimal"}
    )
    assert classifier.model == "gpt-5-mini"
    assert classifier.effort == "minimal"
    assert classifier.max_retries >= 5
    assert isinstance(classifier.client, openai.OpenAI)


def test_strict_schema_closes_every_object_and_requires_every_property() -> None:
    loose = {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "parts": {
                "type": "array",
                "items": {"type": "object", "properties": {"text": {"type": "string"}}},
            },
        },
        "required": ["summary"],
    }
    assert strict_schema(loose) == {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "parts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "additionalProperties": False,
                    "required": ["text"],
                },
            },
        },
        "required": ["summary", "parts"],
        "additionalProperties": False,
    }
    # the task schemas are strict already: unchanged
    assert strict_schema(SCHEMA) == SCHEMA


def test_every_task_schema_is_within_strict_mode_limits() -> None:
    """developers.openai.com structured outputs: <= 1,000 enum values in a schema, and a
    single enum of more than 250 values <= 15,000 characters in total."""
    from openfoodalerts.classify.tasks import RUN_ORDER, make_task
    from openfoodalerts.eval.labelset import default_taxonomy_path, load_taxonomy

    taxonomy = load_taxonomy(default_taxonomy_path())
    for name in RUN_ORDER:
        schema = make_task(name, taxonomy).output_schema()
        assert strict_schema(schema) == schema, name
        enums = [p["enum"] for p in schema["properties"].values() if "enum" in p]
        assert sum(len(e) for e in enums) <= 1000, name
        assert all(len(e) <= 250 or sum(map(len, e)) <= 15000 for e in enums), name


def test_the_registry_builds_gpt_5_mini_from_openai_api_key_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from openfoodalerts.classify.registry import MODELS, make_classifier
    from openfoodalerts.eval.labelset import default_taxonomy_path, load_taxonomy

    assert "gpt-5-mini" in MODELS
    taxonomy = load_taxonomy(default_taxonomy_path())
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    with pytest.raises(ClassifierUnavailable, match="OPENAI_API_KEY"):
        make_classifier("gpt-5-mini", taxonomy)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert make_classifier("gpt-5-mini", taxonomy).model == "gpt-5-mini"
