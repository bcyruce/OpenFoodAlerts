"""Source contracts (spec §3.4): what the parsers rely on in each Source's responses.

Each Source module `sources/<source>/contract.py` describes the fields its parser and
ingest jobs depend on as pydantic models and exposes a `probe` that makes one light set
of requests. A response that does not match raises `ContractViolation`; a Source that
cannot be reached raises `SourceUnreachable`. Messages carry field paths and HTTP statuses
only, never values or URLs: they are shown on /api/health and RASFF responses contain
contact details (and an openFDA URL would carry the API key).
"""

from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

MAX_LISTED_ERRORS = 5


class ContractViolation(Exception):
    """A Source response no longer has the structure our parsers rely on."""


class SourceUnreachable(Exception):
    """A network error or a 5xx after retries: says nothing about the contract."""


class Contract(BaseModel):
    """Base for contract models: extra fields are fine, missing or retyped ones are not."""

    model_config = ConfigDict(extra="allow")


def describe(exc: ValidationError, what: str) -> str:
    """`"detail: reference: Field required; ..."`: paths and messages, never input values."""
    parts = []
    for error in exc.errors(include_url=False, include_input=False, include_context=False):
        path = ".".join(str(p) for p in error["loc"]) or "(root)"
        parts.append(f"{path}: {error['msg']}")
    more = len(parts) - MAX_LISTED_ERRORS
    listed = "; ".join(parts[:MAX_LISTED_ERRORS]) + (f"; and {more} more" if more > 0 else "")
    return f"{what}: {listed}"


def validate[M: Contract](model: type[M], data: Any, what: str) -> M:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ContractViolation(describe(exc, what)) from None


def expect_ok(response: httpx.Response, what: str) -> httpx.Response:
    """200, else unreachable (5xx after retries) or a contract violation (anything else)."""
    if response.status_code >= 500:
        raise SourceUnreachable(f"{what}: HTTP {response.status_code}")
    if response.status_code != 200:
        raise ContractViolation(f"{what}: HTTP {response.status_code}")
    return response


def json_body(response: httpx.Response, what: str) -> Any:
    try:
        return response.json()
    except ValueError:
        content_type = response.headers.get("content-type", "unknown")
        raise ContractViolation(f"{what}: not JSON (content-type {content_type})") from None
