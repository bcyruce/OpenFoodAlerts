"""The pluggable model behind every task (spec §6.4): the `Classifier` interface.

A Classifier turns one `ModelRequest` (the fixed system prompt, the item's user message
and the output JSON schema) into one `ModelResponse` (the parsed JSON output or why there
is none, and the token usage). It knows nothing about tasks, validation, versions or the
database: `classify.run` does that, so every model goes through the same checks. A new
model (another provider, a local model in v1.1) is one class with a `model` name and a
`complete` method; register it in `classify.registry`.
"""

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ModelRequest:
    task: str
    source: str
    # the item's input snapshot, for models that do not read the user message (the fake)
    snapshot: Mapping[str, str]
    # fixed, cacheable prefix: the prompt file's text
    system: str
    # per-item part: the rendered input
    user: str
    output_schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class Usage:
    """Token usage, per response or summed over a run (cost: see docs/implementation-log.md)."""

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    def add(self, other: "Usage") -> None:
        self.requests += other.requests
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_creation_input_tokens += other.cache_creation_input_tokens
        self.cache_read_input_tokens += other.cache_read_input_tokens

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class ModelResponse:
    # the parsed JSON output; None when the model gave none
    output: object | None
    # why there is no usable output (tasks.REFUSAL, TRUNCATED, INVALID_OUTPUT), else None
    failure: str | None = None
    usage: Usage = field(default_factory=Usage)
    request_id: str | None = None


class Classifier(Protocol):
    @property
    def model(self) -> str: ...

    def complete(self, request: ModelRequest) -> ModelResponse: ...


class ClassifierUnavailable(RuntimeError):
    """The model cannot be used at all (no API key, unknown model): nothing was called."""


class ItemFailed(RuntimeError):
    """One request failed in a way that says nothing about the item (e.g. a 400 or an
    exhausted retry budget); nothing is stored, so the next run tries it again."""
