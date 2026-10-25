"""The DeepSeek Flash Classifier, against a stand-in SDK client (no network)."""

import json
from typing import Any

import httpx2
import openai
import pytest

from openfoodalerts.classify.deepseek_model import (
    DEEPSEEK_BASE_URL,
    DEEPSEEK_FLASH,
    DeepSeekClassifier,
    deepseek_schema,
    parse_completion,
)
from openfoodalerts.classify.model import (
    ClassifierUnavailable,
    ItemFailed,
    ModelRequest,
    Usage,
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


def tool_call(arguments: str, name: str = "hazard_category") -> dict[str, Any]:
    return {"id": "call_1", "type": "function", "function": {"name": name, "arguments": arguments}}


def completion(
    *,
    tool_calls: list[dict[str, Any]] | None = None,
    content: str | None = None,
    finish_reason: str = "tool_calls",
    usage: dict[str, Any] | None = None,
    choices: bool = True,
) -> dict[str, Any]:
    """A Chat Completions response body (as `ChatCompletion.model_dump()`)."""
    message = {"role": "assistant", "content": content, "tool_calls": tool_calls}
    return {
        "id": "chatcmpl_1",
        "object": "chat.completion",
        "model": "deepseek-flash",
        "system_fingerprint": "fp_1017",
        "choices": (
            [{"index": 0, "finish_reason": finish_reason, "message": message}] if choices else []
        ),
        "usage": usage,
    }


class Reply:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data

    def model_dump(self) -> dict[str, Any]:
        return self.data


class StandIn:
    """Records `chat.completions.create` calls and answers with queued replies or errors."""

    def __init__(self, *replies: dict[str, Any] | Exception) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []
        self.chat = self
        self.completions = self

    def create(self, **params: Any) -> Reply:
        self.calls.append(params)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return Reply(reply)


def status_error(cls: type[openai.APIStatusError], code: int) -> openai.APIStatusError:
    request = httpx2.Request("POST", "https://api.deepseek.com/beta/chat/completions")
    return cls("boom", response=httpx2.Response(code, request=request), body=None)


def test_the_model_is_deepseek_flash() -> None:
    assert DEEPSEEK_FLASH == "deepseek-flash"
    assert DeepSeekClassifier(client=StandIn()).model == "deepseek-flash"
    # strict tool calls are a beta feature: only on the /beta base URL
    assert DEEPSEEK_BASE_URL == "https://api.deepseek.com/beta"


def test_the_request_puts_the_prompt_first_and_forces_one_strict_tool_call() -> None:
    client = StandIn(completion(tool_calls=[tool_call(json.dumps(OUTPUT))]))
    DeepSeekClassifier(client=client).complete(REQUEST)
    [params] = client.calls
    assert params["model"] == "deepseek-flash"
    # the fixed prompt is the cacheable prefix; the item is the only other message
    assert params["messages"] == [
        {"role": "system", "content": "FIXED SYSTEM PROMPT\n"},
        {"role": "user", "content": REQUEST.user},
    ]
    [tool] = params["tools"]
    assert tool["type"] == "function"
    assert tool["function"]["name"] == "hazard_category"
    assert tool["function"]["strict"] is True
    assert tool["function"]["parameters"] == SCHEMA
    assert params["tool_choice"] == {"type": "function", "function": {"name": "hazard_category"}}
    assert params["max_tokens"] >= 1024
    # thinking is on by default at DeepSeek: off here, so no reasoning tokens are paid for
    assert params["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "reasoning_effort" not in params
    assert not {"temperature", "top_p"} & set(params)


def test_an_effort_turns_thinking_on() -> None:
    client = StandIn(completion(tool_calls=[tool_call(json.dumps(OUTPUT))]))
    DeepSeekClassifier(client=client, effort="low").complete(REQUEST)
    [params] = client.calls
    assert params["extra_body"] == {"thinking": {"type": "enabled"}}
    assert params["reasoning_effort"] == "low"


def test_the_arguments_and_the_usage_come_back_with_cache_hits_split_out() -> None:
    reply = completion(
        tool_calls=[tool_call(json.dumps(OUTPUT))],
        usage={
            "prompt_tokens": 3040,
            "prompt_cache_hit_tokens": 3000,
            "prompt_cache_miss_tokens": 40,
            "completion_tokens": 60,
            "completion_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 3100,
        },
    )
    response = DeepSeekClassifier(client=StandIn(reply)).complete(REQUEST)
    assert response.output == OUTPUT
    assert response.failure is None
    # uncached input 40, output 60, no cache write charge, cache read 3000
    assert response.usage == Usage(0, 40, 60, 0, 3000)
    assert response.request_id == "chatcmpl_1"


def test_usage_without_the_cache_fields_counts_everything_as_uncached() -> None:
    reply = completion(
        tool_calls=[tool_call(json.dumps(OUTPUT))],
        usage={"prompt_tokens": 500, "completion_tokens": 70},
    )
    assert DeepSeekClassifier(client=StandIn(reply)).complete(REQUEST).usage == Usage(
        0, 500, 70, 0, 0
    )


@pytest.mark.parametrize(
    ("reply", "failure", "output"),
    [
        (completion(finish_reason="content_filter"), "refusal", None),
        (
            completion(tool_calls=[tool_call('{"evid')], finish_reason="length"),
            "truncated",
            None,
        ),
        # arguments that are not JSON are kept as text (the abstained row's model_output)
        (completion(tool_calls=[tool_call("not json")]), None, "not json"),
        # an answer in the message text instead of the tool call still counts
        (completion(content=json.dumps(OUTPUT), finish_reason="stop"), None, OUTPUT),
        # DeepSeek's JSON mode may "occasionally return empty content"
        (completion(content="", finish_reason="stop"), "invalid_output", None),
        (completion(choices=False), "invalid_output", None),
    ],
)
def test_no_usable_answer_says_why(
    reply: dict[str, Any], failure: str | None, output: object
) -> None:
    response = DeepSeekClassifier(client=StandIn(reply)).complete(REQUEST)
    assert (response.output, response.failure) == (output, failure)


def test_an_answer_cut_off_for_lack_of_server_capacity_fails_the_item() -> None:
    with pytest.raises(ItemFailed, match="insufficient_system_resource"):
        parse_completion(completion(finish_reason="insufficient_system_resource"))


def test_errors_that_concern_one_request_fail_the_item_only() -> None:
    for error in (
        status_error(openai.BadRequestError, 400),
        status_error(openai.UnprocessableEntityError, 422),
        status_error(openai.RateLimitError, 429),
        status_error(openai.InternalServerError, 500),
        openai.APIConnectionError(request=httpx2.Request("POST", "https://x")),
    ):
        with pytest.raises(ItemFailed):
            DeepSeekClassifier(client=StandIn(error)).complete(REQUEST)


def test_errors_that_concern_every_request_stop_the_run() -> None:
    for error in (
        status_error(openai.AuthenticationError, 401),
        # 402 Insufficient Balance: no request will go through until the account is topped up
        status_error(openai.APIStatusError, 402),
        status_error(openai.PermissionDeniedError, 403),
        status_error(openai.NotFoundError, 404),
    ):
        with pytest.raises(ClassifierUnavailable):
            DeepSeekClassifier(client=StandIn(error)).complete(REQUEST)


def test_without_an_api_key_nothing_is_called_and_the_message_says_what_to_set() -> None:
    with pytest.raises(ClassifierUnavailable, match="DEEPSEEK_API_KEY"):
        DeepSeekClassifier.from_env(environ={})
    # another provider's key is no DeepSeek key
    with pytest.raises(ClassifierUnavailable, match="DEEPSEEK_API_KEY"):
        DeepSeekClassifier.from_env(environ={"DEEPSEEK_API_KEY": " ", "OPENAI_API_KEY": "sk-x"})
    with pytest.raises(ClassifierUnavailable, match="from_env"):
        DeepSeekClassifier().complete(REQUEST)


def test_with_a_key_a_real_client_is_built_without_calling_anything() -> None:
    classifier = DeepSeekClassifier.from_env(
        environ={"DEEPSEEK_API_KEY": "sk-test", "OFA_DEEPSEEK_EFFORT": "low"}
    )
    assert classifier.model == "deepseek-flash"
    assert classifier.effort == "low"
    assert classifier.max_retries >= 5
    assert isinstance(classifier.client, openai.OpenAI)
    assert str(classifier.client.base_url).rstrip("/") == DEEPSEEK_BASE_URL
    # "none" (the default) keeps thinking off
    assert DeepSeekClassifier.from_env(environ={"DEEPSEEK_API_KEY": "sk-test"}).effort is None


def test_deepseek_schema_is_strict_and_drops_the_keywords_deepseek_rejects() -> None:
    loose = {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "minLength": 1, "maxLength": 400},
            "parts": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 3},
        },
    }
    assert deepseek_schema(loose) == {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "parts": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary", "parts"],
        "additionalProperties": False,
    }
    assert deepseek_schema(SCHEMA) == SCHEMA


def test_every_task_schema_is_accepted_unchanged() -> None:
    """api-docs.deepseek.com/guides/tool_calls: strict mode supports object, string, number,
    integer, boolean, array, enum and anyOf; no minLength/maxLength/minItems/maxItems."""
    from openfoodalerts.classify.tasks import RUN_ORDER, make_task
    from openfoodalerts.eval.labelset import default_taxonomy_path, load_taxonomy

    taxonomy = load_taxonomy(default_taxonomy_path())
    for name in RUN_ORDER:
        schema = make_task(name, taxonomy).output_schema()
        assert deepseek_schema(schema) == schema, name


def test_the_registry_builds_deepseek_flash_from_deepseek_api_key_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from openfoodalerts.classify.registry import MODELS, has_batch_api, make_classifier
    from openfoodalerts.eval.labelset import default_taxonomy_path, load_taxonomy

    assert "deepseek-flash" in MODELS
    taxonomy = load_taxonomy(default_taxonomy_path())
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    with pytest.raises(ClassifierUnavailable, match="DEEPSEEK_API_KEY"):
        make_classifier("deepseek-flash", taxonomy)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    assert make_classifier("deepseek-flash", taxonomy).model == "deepseek-flash"
    # DeepSeek has no Batch API
    assert not has_batch_api("deepseek-flash")
    assert has_batch_api("claude-haiku-5-5") and has_batch_api("fake")
