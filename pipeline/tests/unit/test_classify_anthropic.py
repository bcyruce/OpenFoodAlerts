"""The Claude Haiku 5.5 Classifier, against a stand-in SDK client (no network)."""

import json
from typing import Any

import anthropic
import httpx2
import pytest
from anthropic.types import Message

from openfoodalerts.classify.anthropic_model import (
    DEFAULT_MODEL,
    AnthropicClassifier,
)
from openfoodalerts.classify.model import (
    ClassifierUnavailable,
    ItemFailed,
    ModelRequest,
    Usage,
)

REQUEST = ModelRequest(
    task="hazard_category",
    source="openfda",
    snapshot={"reason_for_recall": "Listeria"},
    system="FIXED SYSTEM PROMPT\n",
    user='{"source": "openfda", "input": {"reason_for_recall": "Listeria"}}',
    output_schema={"type": "object", "properties": {}, "additionalProperties": False},
)


def message(content: list[dict[str, Any]], stop_reason: str = "end_turn", **usage: int) -> Message:
    return Message.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": DEFAULT_MODEL,
            "content": content,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0, **usage},
        }
    )


class StandIn:
    """Records `messages.create` calls and answers with queued replies or errors."""

    def __init__(self, *replies: Message | Exception) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []
        self.messages = self

    def create(self, **params: Any) -> Message:
        self.calls.append(params)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def status_error(cls: type[anthropic.APIStatusError], code: int) -> anthropic.APIStatusError:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx2.Response(code, request=request), body=None)


OUTPUT = {
    "evidence_span": "Listeria",
    "category": "pathogenic micro-organisms",
    "confidence": "high",
}


def test_the_first_model_is_claude_haiku_5_5() -> None:
    assert DEFAULT_MODEL == "claude-haiku-5-5"
    assert AnthropicClassifier(client=StandIn()).model == "claude-haiku-5-5"


def test_the_request_caches_the_system_prompt_and_asks_for_the_json_schema() -> None:
    client = StandIn(message([{"type": "text", "text": json.dumps(OUTPUT)}]))
    AnthropicClassifier(client=client, effort="low").complete(REQUEST)
    [params] = client.calls
    assert params["model"] == "claude-haiku-5-5"
    assert params["system"] == [
        {"type": "text", "text": "FIXED SYSTEM PROMPT\n", "cache_control": {"type": "ephemeral"}}
    ]
    assert params["messages"] == [{"role": "user", "content": REQUEST.user}]
    assert params["output_config"] == {
        "effort": "low",
        "format": {"type": "json_schema", "schema": REQUEST.output_schema},
    }
    # Haiku 5.5: no sampling parameters, no prefill, room for adaptive thinking
    assert not {"temperature", "top_p", "top_k", "thinking"} & set(params)
    assert params["max_tokens"] >= 1024


def test_the_json_answer_and_the_usage_come_back() -> None:
    reply = message(
        [
            {"type": "thinking", "thinking": "", "signature": "s"},
            {"type": "text", "text": json.dumps(OUTPUT)},
        ],
        input_tokens=40,
        output_tokens=25,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=3000,
    )
    response = AnthropicClassifier(client=StandIn(reply)).complete(REQUEST)
    assert response.output == OUTPUT
    assert response.failure is None
    assert response.usage == Usage(0, 40, 25, 0, 3000)
    assert response.request_id is None or isinstance(response.request_id, str)


@pytest.mark.parametrize(
    ("reply", "failure", "output"),
    [
        (message([], stop_reason="refusal"), "refusal", None),
        (
            message([{"type": "text", "text": '{"evidence'}], stop_reason="max_tokens"),
            "truncated",
            None,
        ),
        (message([{"type": "text", "text": "not json"}]), None, "not json"),
        (message([]), "invalid_output", None),
    ],
)
def test_no_usable_answer_says_why(reply: Message, failure: str | None, output: object) -> None:
    response = AnthropicClassifier(client=StandIn(reply)).complete(REQUEST)
    assert (response.output, response.failure) == (output, failure)


def test_errors_that_concern_one_request_fail_the_item_only() -> None:
    for error in (
        status_error(anthropic.BadRequestError, 400),
        status_error(anthropic.RateLimitError, 429),
        status_error(anthropic.InternalServerError, 529),
        anthropic.APIConnectionError(request=httpx2.Request("POST", "https://x")),
    ):
        with pytest.raises(ItemFailed):
            AnthropicClassifier(client=StandIn(error)).complete(REQUEST)


def test_errors_that_concern_every_request_stop_the_run() -> None:
    for error in (
        status_error(anthropic.AuthenticationError, 401),
        status_error(anthropic.PermissionDeniedError, 403),
        status_error(anthropic.NotFoundError, 404),
    ):
        with pytest.raises(ClassifierUnavailable):
            AnthropicClassifier(client=StandIn(error)).complete(REQUEST)


def test_without_an_api_key_nothing_is_called_and_the_message_says_what_to_set() -> None:
    with pytest.raises(ClassifierUnavailable, match="ANTHROPIC_API_KEY"):
        AnthropicClassifier.from_env(environ={})
    with pytest.raises(ClassifierUnavailable, match="ANTHROPIC_API_KEY"):
        AnthropicClassifier.from_env(environ={"ANTHROPIC_API_KEY": "  "})


def test_with_a_key_a_real_client_is_built_without_calling_anything() -> None:
    classifier = AnthropicClassifier.from_env(environ={"ANTHROPIC_API_KEY": "sk-test"})
    assert classifier.model == "claude-haiku-5-5"
    assert classifier.max_retries >= 5
