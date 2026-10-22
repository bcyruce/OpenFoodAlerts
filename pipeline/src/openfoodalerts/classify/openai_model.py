"""GPT-5 mini through the official `openai` SDK: the second candidate of spec §6.4.

Request (Responses API, `POST /v1/responses`, SDK `openai` 3.x; checked against
developers.openai.com on 2026-10-25, see docs/implementation-log.md ### 21):

- `instructions` is the prompt file's text and `input` the item's user message, so the
  fixed prefix comes first. OpenAI caches prompt prefixes automatically (no cache write
  charge); `prompt_cache_key` = one key per task keeps requests with the same prefix on
  the same cache. `store: false`: nothing is kept at OpenAI for later retrieval.
- Output: Structured Outputs (`text.format` json_schema, `strict: true`) with the task's
  schema, made strict-mode compatible by `strict_schema` (every object
  `additionalProperties: false` and every property required; the task schemas already
  are). The code still validates the answer (`Task.check`).
- GPT-5 mini is a reasoning model: `reasoning.effort` (default "low" here, the same
  classification route as Haiku's effort; `OFA_OPENAI_EFFORT` overrides) and
  `max_output_tokens`, which counts reasoning tokens too. No `temperature` / `top_p`.
- A refusal (`refusal` content) and `incomplete` with reason `content_filter` become
  abstains with reason `refusal`; `incomplete` for `max_output_tokens` becomes `truncated`.
  A `failed` response fails the item (nothing stored, retried next run).

Usage is normalised to the Anthropic meaning of `Usage`: OpenAI's `input_tokens` include
the cached ones, so `input_tokens` here = uncached input, `cache_read_input_tokens` =
`input_tokens_details.cached_tokens`, `cache_creation_input_tokens` = 0 (OpenAI does not
charge cache writes); `output_tokens` include the reasoning tokens (billed as output).

Retries: the SDK retries 408/409/429/5xx and connection errors with exponential backoff
(`max_retries` 6). What still fails fails the item (`ItemFailed`); 401/403/404 stop the run
(`ClassifierUnavailable`). Only `OPENAI_API_KEY` is read. The Batch API (ticket 21) sends
the same `request_params` as each line's `body` and parses each output line's body with
`parse_response`.

**GPT-5 mini is deprecated** (OpenAI, 2026-06-11): `gpt-5-mini` shuts down on
2026-12-11, replacement `gpt-5.6-terra` (eval/model_prices.json).
"""

import json
import os
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

import openai

from openfoodalerts.classify.batch import BatchRequest, BatchResult, BatchStatus
from openfoodalerts.classify.model import (
    ClassifierUnavailable,
    ItemFailed,
    ModelRequest,
    ModelResponse,
    Usage,
)
from openfoodalerts.classify.registry import GPT_5_MINI
from openfoodalerts.classify.tasks import INVALID_OUTPUT, REFUSAL, TRUNCATED

__all__ = ["GPT_5_MINI", "OpenAIBatches", "OpenAIClassifier", "parse_response", "strict_schema"]

DEFAULT_EFFORT = "low"
DEFAULT_MAX_OUTPUT_TOKENS = 2048
DEFAULT_MAX_RETRIES = 6
DEFAULT_TIMEOUT_S = 120.0


def strict_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """A copy of a JSON schema that Structured Outputs' strict mode accepts: every object
    closed (`additionalProperties: false`) with all its properties required."""
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "properties" and isinstance(value, Mapping):
            out[key] = {name: strict_schema(sub) for name, sub in value.items()}
        elif key == "items" and isinstance(value, Mapping):
            out[key] = strict_schema(value)
        else:
            out[key] = value
    if out.get("type") == "object":
        out["additionalProperties"] = False
        out["required"] = list(out.get("properties", {}))
    return out


def usage_of(usage: Mapping[str, Any] | None) -> Usage:
    if not usage:
        return Usage()
    cached = (usage.get("input_tokens_details") or {}).get("cached_tokens") or 0
    return Usage(
        input_tokens=(usage.get("input_tokens") or 0) - cached,
        output_tokens=usage.get("output_tokens") or 0,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=cached,
    )


def parse_response(body: Mapping[str, Any]) -> ModelResponse:
    """A Responses API response body -> ModelResponse; raises ItemFailed for `failed`."""
    usage = usage_of(body.get("usage"))
    request_id = body.get("id")
    status = body.get("status")
    if status == "failed":
        raise ItemFailed(f"response failed: {body.get('error')}")
    if status == "incomplete":
        reason = (body.get("incomplete_details") or {}).get("reason")
        failure = REFUSAL if reason == "content_filter" else TRUNCATED
        return ModelResponse(None, failure, usage, request_id)
    texts: list[str] = []
    for item in body.get("output") or ():
        if item.get("type") != "message":
            continue
        for content in item.get("content") or ():
            if content.get("type") == "refusal":
                return ModelResponse(None, REFUSAL, usage, request_id)
            if content.get("type") == "output_text" and content.get("text") is not None:
                texts.append(content["text"])
    if not texts:
        return ModelResponse(None, INVALID_OUTPUT, usage, request_id)
    text = "".join(texts)
    try:
        output: object = json.loads(text)
    except json.JSONDecodeError:
        output = text  # kept as text: stored as the abstained row's model_output
    return ModelResponse(output, None, usage, request_id)


class OpenAIClassifier:
    def __init__(
        self,
        model: str = GPT_5_MINI,
        *,
        client: Any = None,
        effort: str = DEFAULT_EFFORT,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        self.model = model
        self.effort = effort
        self.max_output_tokens = max_output_tokens
        self.max_retries = max_retries
        # any object with `responses.create(**params)` (tests pass a stand-in)
        self.client = client

    @classmethod
    def from_env(
        cls,
        model: str = GPT_5_MINI,
        *,
        environ: Mapping[str, str] | None = None,
        **options: Any,
    ) -> "OpenAIClassifier":
        """A classifier with a real client; fails before any call without OPENAI_API_KEY."""
        env = os.environ if environ is None else environ
        key = (env.get("OPENAI_API_KEY") or "").strip()
        if not key:
            raise ClassifierUnavailable(
                f"OPENAI_API_KEY is not set: {model} needs an OpenAI API key "
                "(export OPENAI_API_KEY=... or put it in .env); nothing was called"
            )
        effort = options.pop("effort", None) or env.get("OFA_OPENAI_EFFORT") or DEFAULT_EFFORT
        classifier = cls(model, effort=effort, **options)
        classifier.client = openai.OpenAI(
            api_key=key, max_retries=classifier.max_retries, timeout=DEFAULT_TIMEOUT_S
        )
        return classifier

    def request_params(self, request: ModelRequest) -> dict[str, Any]:
        """The Responses API parameters of one request (also a Batch line's `body`)."""
        return {
            "model": self.model,
            "instructions": request.system,
            "input": request.user,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": request.task,
                    "schema": strict_schema(request.output_schema),
                    "strict": True,
                }
            },
            "reasoning": {"effort": self.effort},
            "max_output_tokens": self.max_output_tokens,
            "prompt_cache_key": f"openfoodalerts-{request.task}",
            "store": False,
        }

    def complete(self, request: ModelRequest) -> ModelResponse:
        if self.client is None:
            raise ClassifierUnavailable("no OpenAI client (use OpenAIClassifier.from_env)")
        try:
            response = self.client.responses.create(**self.request_params(request))
        except (
            openai.AuthenticationError,
            openai.PermissionDeniedError,
            openai.NotFoundError,
        ) as exc:
            raise ClassifierUnavailable(f"{self.model}: {type(exc).__name__}: {exc}") from exc
        except (openai.APIStatusError, openai.APIConnectionError) as exc:
            raise ItemFailed(f"{self.model}: {type(exc).__name__}: {exc}") from exc
        return parse_response(response.model_dump())


@contextmanager
def _api_errors(model: str) -> Iterator[None]:
    """401/403/404 -> ClassifierUnavailable (stop), other API errors -> ItemFailed."""
    try:
        yield
    except (openai.AuthenticationError, openai.PermissionDeniedError, openai.NotFoundError) as exc:
        raise ClassifierUnavailable(f"{model}: {type(exc).__name__}: {exc}") from exc
    except (openai.APIStatusError, openai.APIConnectionError) as exc:
        raise ItemFailed(f"{model}: {type(exc).__name__}: {exc}") from exc


# A batch is over (no more results will come) in these states.
_ENDED = ("completed", "failed", "expired", "cancelled")


def _line_result(line: Mapping[str, Any]) -> BatchResult:
    """One line of a batch's output or error file."""
    custom_id = str(line["custom_id"])
    error = line.get("error")
    if error:
        return BatchResult(custom_id, None, f"error: {error.get('code')}: {error.get('message')}")
    response = line.get("response") or {}
    if response.get("status_code") != 200:
        message = ((response.get("body") or {}).get("error") or {}).get("message")
        return BatchResult(custom_id, None, f"HTTP {response.get('status_code')}: {message}")
    try:
        return BatchResult(custom_id, parse_response(response["body"]))
    except ItemFailed as exc:
        return BatchResult(custom_id, None, str(exc))


class OpenAIBatches:
    """The Batch API (`/v1/batches` over `/v1/responses`, 50% of the standard price) for
    `ofa classify --batch`: the requests go up as a JSONL file (`purpose: batch`), one line
    `{custom_id, method: POST, url: /v1/responses, body}` per request with the synchronous
    `request_params` as body; results come from the output and error files, in any order,
    matched by custom_id (`classify.batch`). A batch that failed, expired or was cancelled
    is over; requests without a result line are then failed and retried next time."""

    provider = "openai"

    def __init__(self, classifier: OpenAIClassifier) -> None:
        self.classifier = classifier

    @property
    def model(self) -> str:
        return self.classifier.model

    @property
    def _client(self) -> Any:
        if self.classifier.client is None:
            raise ClassifierUnavailable("no OpenAI client (use OpenAIClassifier.from_env)")
        return self.classifier.client

    def params(self, request: ModelRequest) -> dict[str, Any]:
        return self.classifier.request_params(request)

    def submit(self, requests: Sequence[BatchRequest]) -> str:
        lines = "".join(
            json.dumps(
                {
                    "custom_id": r.custom_id,
                    "method": "POST",
                    "url": "/v1/responses",
                    "body": r.params,
                },
                ensure_ascii=False,
            )
            + "\n"
            for r in requests
        )
        with _api_errors(self.model):
            upload = self._client.files.create(
                file=("openfoodalerts-batch.jsonl", lines.encode()), purpose="batch"
            )
            batch = self._client.batches.create(
                input_file_id=upload.id,
                endpoint="/v1/responses",
                completion_window="24h",
                metadata={"app": "openfoodalerts", "first_custom_id": requests[0].custom_id},
            )
        return str(batch.id)

    def status(self, batch_id: str) -> BatchStatus:
        with _api_errors(self.model):
            batch = self._client.batches.retrieve(batch_id)
        c = batch.request_counts
        counts = f": completed {c.completed}, failed {c.failed} of {c.total}" if c else ""
        return BatchStatus(batch.status in _ENDED, f"{batch.status}{counts}")

    def results(self, batch_id: str) -> Iterator[BatchResult]:
        with _api_errors(self.model):
            batch = self._client.batches.retrieve(batch_id)
            for file_id in (batch.output_file_id, batch.error_file_id):
                if not file_id:
                    continue
                for line in self._client.files.content(file_id).text.splitlines():
                    if line.strip():
                        yield _line_result(json.loads(line))
