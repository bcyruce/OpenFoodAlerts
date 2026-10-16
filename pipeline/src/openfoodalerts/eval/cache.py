"""Cached model outputs: `eval/cache/{model}/{prompt_version}.jsonl` (spec §7.3).

One JSON object per line and per (item, task), keys in the order of `ModelOutput`'s fields:

    item_id, task, value, confidence, abstained, evidence_span, input_hash, model,
    prompt_version, schema_version, taxonomy_version, created_at

- `task` is a spec §6.1 task name (hazard_category, product_category, hazard,
  origin_country, product_type).
- `value` is the output as text (a T1 label, a RASFF Product category, a verbatim span, an
  ISO2 code or "unknown", a Product type), `null` when `abstained` is true.
- `confidence` is high / medium / low (`null` when abstained).
- `input_hash` is `openfoodalerts.classify.input_hash.input_hash` of the item's frozen input;
  the harness ignores (and counts as stale) lines whose hash no longer matches items.csv.
- `created_at` is ISO 8601.

The file is sorted by (task, item_id), UTF-8, LF. `make eval-refresh` (ticket 16) writes it
through `write_outputs`; `make eval` only reads it.
"""

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from openfoodalerts.eval.files import TASKS
from openfoodalerts.eval.metrics import CONFIDENCES


class CacheError(ValueError):
    """A cache file that does not follow the format."""


@dataclass(frozen=True)
class ModelOutput:
    item_id: str
    task: str
    value: str | None
    confidence: str | None
    abstained: bool
    evidence_span: str | None
    input_hash: str
    model: str
    prompt_version: str
    schema_version: str
    taxonomy_version: str
    created_at: str


FIELDS = tuple(f.name for f in fields(ModelOutput))


@dataclass(frozen=True)
class CachedRun:
    model: str
    prompt_version: str
    path: Path
    outputs: list[ModelOutput]


def cache_path(cache_dir: Path, model: str, prompt_version: str) -> Path:
    for part in (model, prompt_version):
        if not part or "/" in part or "\\" in part or part.startswith("."):
            raise ValueError(f"not usable as a file name: {part!r}")
    return cache_dir / model / f"{prompt_version}.jsonl"


def _parse(line: str, where: str, model: str, prompt_version: str) -> ModelOutput:
    try:
        data: Any = json.loads(line)
    except json.JSONDecodeError as exc:
        raise CacheError(f"{where}: not JSON ({exc.msg})") from exc
    if not isinstance(data, dict) or set(data) != set(FIELDS):
        raise CacheError(f"{where}: expected the keys {', '.join(FIELDS)}")
    if (data["model"], data["prompt_version"]) != (model, prompt_version):
        raise CacheError(f"{where}: model / prompt_version differ from the file's path")
    if data["task"] not in TASKS:
        raise CacheError(f"{where}: unknown task {data['task']!r}")
    if not isinstance(data["abstained"], bool):
        raise CacheError(f"{where}: abstained must be true or false")
    if data["confidence"] is not None and data["confidence"] not in CONFIDENCES:
        raise CacheError(f"{where}: confidence must be high, medium, low or null")
    if not data["abstained"] and not isinstance(data["value"], str):
        raise CacheError(f"{where}: value must be text unless abstained")
    return ModelOutput(**data)


def read_run(path: Path) -> CachedRun:
    model, prompt_version = path.parent.name, path.stem
    outputs = []
    with path.open(encoding="utf-8") as f:
        for number, line in enumerate(f, start=1):
            if line.strip():
                where = f"{path.parent.name}/{path.name}:{number}"
                outputs.append(_parse(line, where, model, prompt_version))
    return CachedRun(model, prompt_version, path, outputs)


def read_cache(cache_dir: Path) -> list[CachedRun]:
    """Every `{model}/{prompt_version}.jsonl` under cache_dir, sorted by path."""
    if not cache_dir.is_dir():
        return []
    return [read_run(p) for p in sorted(cache_dir.glob("*/*.jsonl"))]


def write_outputs(cache_dir: Path, outputs: Iterable[ModelOutput]) -> Path:
    """Merge outputs of one model and prompt version into its cache file: a new
    output replaces the cached one for the same (item, task)."""
    new = list(outputs)
    keys = {(p.model, p.prompt_version) for p in new}
    if len(keys) != 1:
        raise ValueError("write_outputs takes outputs of one model and prompt version")
    [(model, prompt_version)] = keys
    path = cache_path(cache_dir, model, prompt_version)
    merged = {(p.task, p.item_id): p for p in (read_run(path).outputs if path.exists() else [])}
    merged |= {(p.task, p.item_id): p for p in new}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for key in sorted(merged):
            f.write(json.dumps(asdict(merged[key]), ensure_ascii=False) + "\n")
    return path
