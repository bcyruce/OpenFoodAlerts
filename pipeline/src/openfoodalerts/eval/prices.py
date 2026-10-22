"""The verified model price table (`eval/model_prices.json`, spec §16 V1) and token cost.

`Rates` are USD per million tokens for the four kinds of tokens `classify.model.Usage`
counts: uncached input, cache writes, cache reads and output (OpenAI usage is normalised
to the same meaning in `classify.openai_model`). Each model has a standard and a Batch
table.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openfoodalerts.classify.model import Usage
from openfoodalerts.eval.job import REPO_ROOT

PRICES_FILE = REPO_ROOT / "eval" / "model_prices.json"

# The per-request token profile used when a model has no measured usage yet (assumed, not
# measured; docs/implementation-log.md ### 16): the item's message, the cached prompt
# prefix, a short JSON answer plus some reasoning.
NOMINAL_REQUEST = Usage(
    requests=1,
    input_tokens=200,
    output_tokens=300,
    cache_creation_input_tokens=0,
    cache_read_input_tokens=4000,
)


@dataclass(frozen=True)
class Rates:
    input: float
    cache_write: float
    cache_read: float
    output: float


@dataclass(frozen=True)
class ModelPrices:
    model: str
    provider: str
    standard: Rates
    batch: Rates
    sources: tuple[str, ...]
    # announced shutdown date (YYYY-MM-DD), if the provider deprecated the model
    shutdown: str | None = None


@dataclass(frozen=True)
class PriceTable:
    verified_on: str
    models: dict[str, ModelPrices]
    path: Path


def _rates(data: dict[str, Any]) -> Rates:
    return Rates(
        input=float(data["input"]),
        cache_write=float(data["cache_write"]),
        cache_read=float(data["cache_read"]),
        output=float(data["output"]),
    )


def load_prices(path: Path = PRICES_FILE) -> PriceTable:
    data = json.loads(path.read_text(encoding="utf-8"))
    models = {
        name: ModelPrices(
            model=name,
            provider=m["provider"],
            standard=_rates(m["standard"]),
            batch=_rates(m["batch"]),
            sources=tuple(m["sources"]),
            shutdown=(m.get("deprecation") or {}).get("shutdown"),
        )
        for name, m in data["models"].items()
    }
    return PriceTable(verified_on=data["verified_on"], models=models, path=path)


def cost_usd(usage: Usage, rates: Rates) -> float:
    return (
        usage.input_tokens * rates.input
        + usage.cache_creation_input_tokens * rates.cache_write
        + usage.cache_read_input_tokens * rates.cache_read
        + usage.output_tokens * rates.output
    ) / 1_000_000
