"""DeepSeek Flash (`deepseek-flash`, V4.1 Flash) through the `openai` SDK: the second
candidate of spec §6.4 since GPT-5 mini retires (checked against api-docs.deepseek.com on
2026-10-25, see docs/implementation-log.md "### DeepSeek challenger").

Request (OpenAI-compatible Chat Completions on `https://api.deepseek.com/beta`):

- `messages` = the prompt file's text as the system message, then the item's user
  message, so the fixed prefix comes first. DeepSeek caches prefixes automatically and
  best-effort (no cache key, no cache write charge).
- Output: DeepSeek's `response_format` has `json_object` only, which does not enforce a
  schema. The one documented enforcement is a function tool with `strict: true` (a beta
  feature, hence the /beta base URL), so the task's schema is the parameters of a single
  tool the model is forced to call (`tool_choice`). `deepseek_schema` makes it strict and
  drops the keywords strict mode rejects. The code still validates the answer.
- Thinking is on by default at DeepSeek; it is turned off here (`thinking: disabled`), the
  same route as Haiku's classification. `OFA_DEEPSEEK_EFFORT` = low / high / max turns it
  on at that effort (reasoning tokens are then billed as output).
- `finish_reason` `content_filter` becomes an abstain with reason `refusal`, `length`
  becomes `truncated`; `insufficient_system_resource` (cut off by DeepSeek) fails the item.

Usage is normalised to the Anthropic meaning of `Usage`: `input_tokens` =
`prompt_cache_miss_tokens`, `cache_read_input_tokens` = `prompt_cache_hit_tokens`,
`cache_creation_input_tokens` = 0; `output_tokens` = `completion_tokens` (with reasoning).

Retries: the SDK retries 408/409/429/5xx and connection errors (`max_retries` 6). What
still fails fails the item (`ItemFailed`); 401/402 (no balance)/403/404 stop the run
(`ClassifierUnavailable`). Only `DEEPSEEK_API_KEY` is read.

There is no Batch API (`registry.has_batch_api`): the backfill runs synchronously
(`ofa classify --concurrency N`); off-peak hours cost half (eval/model_prices.json).
`deepseek-flash` has no pinned snapshot: DeepSeek moves it to each new version.
"""

import json
import os
from collections.abc import Mapping
from typing import Any

import openai

from openfoodalerts.classify.model import (
    ClassifierUnavailable,
    ItemFailed,
    ModelRequest,
    ModelResponse,
    Usage,
)
from openfoodalerts.classify.openai_model import strict_schema
from openfoodalerts.classify.registry import DEEPSEEK_FLASH
from openfoodalerts.classify.tasks import INVALID_OUTPUT, REFUSAL, TRUNCATED

__all__ = [
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_FLASH",
    "DeepSeekClassifier",
    "deepseek_schema",
    "parse_completion",
]

DEEPSEEK_BASE_URL = "https://api.deepseek.com/beta"
DEFAULT_MAX_OUTPUT_TOKENS = 2048
DEFAULT_MAX_RETRIES = 6
DEFAULT_TIMEOUT_S = 120.0
# JSON schema keywords DeepSeek's strict mode does not support (api-docs.deepseek.com
# guides/tool_calls); none of the task schemas use them.
_UNSUPPORTED = ("minLength", "maxLength", "minItems", "maxItems")


def deepseek_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """`strict_schema` without the keywords DeepSeek's strict mode rejects."""

    def drop(node: Any) -> Any:
        if isinstance(node, Mapping):
            return {k: drop(v) for k, v in node.items() if k not in _UNSUPPORTED}
        if isinstance(node, list):
            return [drop(v) for v in node]
        return node

    out: dict[str, Any] = drop(strict_schema(schema))
    return out


def usage_of(usage: Mapping[str, Any] | None) -> Usage:
    if not usage:
        return Usage()
    hit = usage.get("prompt_cache_hit_tokens") or 0
    miss = usage.get("prompt_cache_miss_tokens")
    return Usage(
        input_tokens=miss if miss is not None else (usage.get("prompt_tokens") or 0) - hit,
        output_tokens=usage.get("completion_tokens") or 0,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=hit,
    )


def parse_completion(body: Mapping[str, Any]) -> ModelResponse:
    """A Chat Completions response body -> ModelResponse; raises ItemFailed when DeepSeek
    cut the answer off for lack of capacity."""
    usage = usage_of(body.get("usage"))
    request_id = body.get("id")
    choices = body.get("choices") or ()
    if not choices:
        return ModelResponse(None, INVALID_OUTPUT, usage, request_id)
    choice = choices[0]
    reason = choice.get("finish_reason")
    if reason == "insufficient_system_resource":
        raise ItemFailed("answer cut off: insufficient_system_resource")
    if reason == "content_filter":
        return ModelResponse(None, REFUSAL, usage, request_id)
    if reason == "length":
        return ModelResponse(None, TRUNCATED, usage, request_id)
    message = choice.get("message") or {}
    calls = message.get("tool_calls") or ()
    text = calls[0]["function"].get("arguments") if calls else message.get("content")
    if not text:
        return ModelResponse(None, INVALID_OUTPUT, usage, request_id)
    try:
        output: object = json.loads(text)
    except json.JSONDecodeError:
        output = text  # kept as text: stored as the abstained row's model_output
    return ModelResponse(output, None, usage, request_id)


class DeepSeekClassifier:
    def __init__(
        self,
        model: str = DEEPSEEK_FLASH,
        *,
        client: Any = None,
        effort: str | None = None,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        self.model = model
        # None: thinking off; low / high / max: thinking on at that effort
        self.effort = effort
        self.max_output_tokens = max_output_tokens
        self.max_retries = max_retries
        # any object with `chat.completions.create(**params)` (tests pass a stand-in)
        self.client = client

    @classmethod
    def from_env(
        cls,
        model: str = DEEPSEEK_FLASH,
        *,
        environ: Mapping[str, str] | None = None,
        **options: Any,
    ) -> "DeepSeekClassifier":
        """A classifier with a real client; fails before any call without DEEPSEEK_API_KEY."""
        env = os.environ if environ is None else environ
        key = (env.get("DEEPSEEK_API_KEY") or "").strip()
        if not key:
            raise ClassifierUnavailable(
                f"DEEPSEEK_API_KEY is not set: {model} needs a DeepSeek API key "
                "(export DEEPSEEK_API_KEY=... or put it in .env); nothing was called"
            )
        effort = options.pop("effort", None) or env.get("OFA_DEEPSEEK_EFFORT") or None
        classifier = cls(model, effort=None if effort == "none" else effort, **options)
        classifier.client = openai.OpenAI(
            api_key=key,
            base_url=DEEPSEEK_BASE_URL,
            max_retries=classifier.max_retries,
            timeout=DEFAULT_TIMEOUT_S,
        )
        return classifier

    def request_params(self, request: ModelRequest) -> dict[str, Any]:
        """The Chat Completions parameters of one request."""
        params: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": request.task,
                        "description": "Record the answer.",
                        "strict": True,
                        "parameters": deepseek_schema(request.output_schema),
                    },
                }
            ],
            "tool_choice": {"type": "function", "function": {"name": request.task}},
            "max_tokens": self.max_output_tokens,
            "extra_body": {"thinking": {"type": "disabled" if self.effort is None else "enabled"}},
        }
        if self.effort is not None:
            params["reasoning_effort"] = self.effort
        return params

    def complete(self, request: ModelRequest) -> ModelResponse:
        if self.client is None:
            raise ClassifierUnavailable("no DeepSeek client (use DeepSeekClassifier.from_env)")
        try:
            response = self.client.chat.completions.create(**self.request_params(request))
        except (
            openai.AuthenticationError,
            openai.PermissionDeniedError,
            openai.NotFoundError,
        ) as exc:
            raise ClassifierUnavailable(f"{self.model}: {type(exc).__name__}: {exc}") from exc
        except openai.APIStatusError as exc:
            if exc.status_code == 402:  # Insufficient Balance: every request would fail
                raise ClassifierUnavailable(f"{self.model}: insufficient balance: {exc}") from exc
            raise ItemFailed(f"{self.model}: {type(exc).__name__}: {exc}") from exc
        except openai.APIConnectionError as exc:
            raise ItemFailed(f"{self.model}: {type(exc).__name__}: {exc}") from exc
        return parse_completion(response.model_dump())
