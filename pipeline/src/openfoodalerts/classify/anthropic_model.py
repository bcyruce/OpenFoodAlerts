"""Claude through the Anthropic SDK; the first model is Claude Haiku 5.5 (spec §6.4).

Request (Messages API, SDK `anthropic` 2.x, API version 2026-10-21):

- `system` is the prompt file's text as one block with `cache_control` ephemeral, so the
  fixed prefix (task, taxonomy, rules, 15 examples; well above Haiku 5.5's 512-token
  minimum) is cached and later requests read it at the cache rate; the item is the only
  user message. Nothing variable (dates, ids) is in the system prompt.
- Output: structured outputs (`output_config.format` json_schema) with the task's schema:
  the category is an enum of the taxonomy labels plus `abstain`, so the answer is valid
  JSON in the first text block. The code still validates it (`tasks.check`). Chosen over
  a forced tool call, which skips thinking on Haiku 5.5 and is rejected by newer models.
- Haiku 5.5 runs adaptive thinking by default; `output_config.effort` sets how much
  (default here "low", a classification route; try "medium" on dev once a key exists).
  No `temperature` / `top_p` / `top_k` (rejected on API 2026-10-21) and no prefill.
  `max_tokens` leaves room for thinking before the short JSON answer.
- `stop_reason` "refusal" (Haiku 5.5 has safety classifiers and no server-side fallback)
  and "max_tokens" become abstains with that reason.

Retries: the SDK retries 408/409/429/5xx and connection errors with exponential backoff
(`max_retries`, default here 6). What still fails afterwards fails the item (`ItemFailed`:
nothing stored, retried on the next run); 401/403/404 stop the run (`ClassifierUnavailable`).
Backfill should go through the Message Batches API at half price (ticket 21): it takes the
same `request_params`.
"""

import json
import os
from collections.abc import Mapping
from typing import Any

import anthropic
from anthropic.types import Message

from openfoodalerts.classify.model import (
    ClassifierUnavailable,
    ItemFailed,
    ModelRequest,
    ModelResponse,
    Usage,
)
from openfoodalerts.classify.registry import DEFAULT_MODEL
from openfoodalerts.classify.tasks import INVALID_OUTPUT, REFUSAL, TRUNCATED

__all__ = ["DEFAULT_MODEL", "AnthropicClassifier", "parse_message"]

DEFAULT_EFFORT = "low"
DEFAULT_MAX_TOKENS = 2048
DEFAULT_MAX_RETRIES = 6
DEFAULT_TIMEOUT_S = 120.0


def usage_of(message: Message) -> Usage:
    u = message.usage
    return Usage(
        input_tokens=u.input_tokens or 0,
        output_tokens=u.output_tokens or 0,
        cache_creation_input_tokens=u.cache_creation_input_tokens or 0,
        cache_read_input_tokens=u.cache_read_input_tokens or 0,
    )


def parse_message(message: Message) -> ModelResponse:
    usage = usage_of(message)
    request_id = getattr(message, "_request_id", None)
    if message.stop_reason == "refusal":
        return ModelResponse(None, REFUSAL, usage, request_id)
    if message.stop_reason == "max_tokens":
        return ModelResponse(None, TRUNCATED, usage, request_id)
    text = next((block.text for block in message.content if block.type == "text"), None)
    if text is None:
        return ModelResponse(None, INVALID_OUTPUT, usage, request_id)
    try:
        output: object = json.loads(text)
    except json.JSONDecodeError:
        # kept as text: stored as the abstained row's model_output for review
        output = text
    return ModelResponse(output, None, usage, request_id)


class AnthropicClassifier:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        client: Any = None,
        effort: str = DEFAULT_EFFORT,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        # any object with `messages.create(**params) -> Message` (tests pass a stand-in)
        self._client = client

    @classmethod
    def from_env(
        cls,
        model: str = DEFAULT_MODEL,
        *,
        environ: Mapping[str, str] | None = None,
        **options: Any,
    ) -> "AnthropicClassifier":
        """A classifier with a real client; fails before any call without ANTHROPIC_API_KEY."""
        env = os.environ if environ is None else environ
        key = (env.get("ANTHROPIC_API_KEY") or "").strip()
        if not key:
            raise ClassifierUnavailable(
                f"ANTHROPIC_API_KEY is not set: {model} needs an Anthropic API key "
                "(export ANTHROPIC_API_KEY=... or put it in .env); nothing was called"
            )
        effort = options.pop("effort", None) or env.get("OFA_CLASSIFY_EFFORT") or DEFAULT_EFFORT
        classifier = cls(model, effort=effort, **options)
        classifier._client = anthropic.Anthropic(
            api_key=key, max_retries=classifier.max_retries, timeout=DEFAULT_TIMEOUT_S
        )
        return classifier

    def request_params(self, request: ModelRequest) -> dict[str, Any]:
        """The Messages API parameters of one request (also a Batch request's params)."""
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": [
                {"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}
            ],
            "messages": [{"role": "user", "content": request.user}],
            "output_config": {
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": request.output_schema},
            },
        }

    def complete(self, request: ModelRequest) -> ModelResponse:
        if self._client is None:
            raise ClassifierUnavailable("no Anthropic client (use AnthropicClassifier.from_env)")
        try:
            message = self._client.messages.create(**self.request_params(request))
        except (
            anthropic.AuthenticationError,
            anthropic.PermissionDeniedError,
            anthropic.NotFoundError,
        ) as exc:
            raise ClassifierUnavailable(f"{self.model}: {type(exc).__name__}: {exc}") from exc
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
            raise ItemFailed(f"{self.model}: {type(exc).__name__}: {exc}") from exc
        return parse_message(message)
