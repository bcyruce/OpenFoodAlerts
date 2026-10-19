"""The human factual-consistency check of T6 summaries (spec §7.2: 50 summaries, no ROUGE).

1. `ofa factcheck-sample` draws a reproducible sample of cached summaries of eval items
   (`sample_factcheck`) into eval/factcheck/t6.csv, keeping judgments already made.
2. The owner judges each row, in eval/factcheck_app.py (Streamlit) or by editing the CSV:
   `consistent` = yes when every statement of the summary is supported by the source
   text and nothing is added (no new facts, no severity), else no, with a `problem` note.
3. `make eval` reports the result as the `t6_factcheck` block of latest.json
   (`factcheck_report`; format in eval/README.md).

The sample: the non-abstained summaries of one model and prompt version on one split
whose input_hash matches the item's frozen input, split into the five strata
(NVWA en/nl/zh, openFDA en/nl) and taken round-robin, each stratum in a fixed order
(sha256 of seed, item and task), so the strata are equally represented and the same cache
always gives the same sample.
"""

import csv
import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from openfoodalerts.classify.input_hash import input_hash
from openfoodalerts.classify.summary import SUMMARY_TASKS
from openfoodalerts.eval import metrics
from openfoodalerts.eval.cache import ModelOutput
from openfoodalerts.eval.files import ItemRow

SAMPLE_SIZE = 50
SEED = 20261025
# relative to eval/
FACTCHECK_FILE = "factcheck/t6.csv"


@dataclass(frozen=True)
class FactCheckRow:
    item_id: str
    split: str
    source: str
    task: str
    locale: str
    model: str
    prompt_version: str
    input_hash: str
    input: dict[str, str]
    summary: str
    # the owner's judgment: "yes", "no" or "" (not checked yet)
    consistent: str = ""
    problem: str = ""
    checker: str = ""
    checked_at: str = ""


def current_hash(item: ItemRow, model: str, prompt_version: str) -> str:
    return input_hash(item.input, prompt_version=prompt_version, model=model, taxonomy_version="")


def _order(seed: int, output: ModelOutput) -> str:
    return hashlib.sha256(f"{seed}:{output.item_id}:{output.task}".encode()).hexdigest()


def sample_factcheck(
    items: Sequence[ItemRow],
    outputs: Iterable[ModelOutput],
    *,
    model: str,
    prompt_version: str,
    split: str,
    n: int = SAMPLE_SIZE,
    seed: int = SEED,
) -> list[FactCheckRow]:
    by_id = {i.item_id: i for i in items if i.split == split}
    strata: dict[tuple[str, str], list[ModelOutput]] = defaultdict(list)
    for o in outputs:
        it = by_id.get(o.item_id)
        if (
            it is None
            or o.task not in SUMMARY_TASKS
            or (o.model, o.prompt_version) != (model, prompt_version)
            or o.abstained
            or o.value is None
            or o.input_hash != current_hash(it, model, prompt_version)
        ):
            continue
        strata[(it.source, o.task)].append(o)
    queues = [sorted(strata[key], key=lambda o: _order(seed, o)) for key in sorted(strata)]
    picked: list[ModelOutput] = []
    while len(picked) < n and any(queues):
        for queue in queues:
            if queue and len(picked) < n:
                picked.append(queue.pop(0))
    rows = [
        FactCheckRow(
            item_id=o.item_id,
            split=split,
            source=by_id[o.item_id].source,
            task=o.task,
            locale=o.task.removeprefix("summary_"),
            model=model,
            prompt_version=prompt_version,
            input_hash=o.input_hash,
            input=dict(by_id[o.item_id].input),
            summary=str(o.value),
        )
        for o in picked
    ]
    return sorted(rows, key=_row_order)


def _row_order(r: FactCheckRow) -> tuple[str, ...]:
    return (r.model, r.prompt_version, r.split, r.source, r.locale, r.item_id)


def _key(r: FactCheckRow) -> tuple[str, str, str, str]:
    return (r.model, r.prompt_version, r.item_id, r.task)


def merge_sample(
    existing: Sequence[FactCheckRow], sample: Sequence[FactCheckRow]
) -> list[FactCheckRow]:
    """The new sample of one model and prompt version, merged into the file's rows:

    - a sampled summary that was judged before (same item, task, input_hash and text)
      keeps its judgment; if the text changed, the old judgment is dropped;
    - judged rows of the same model and prompt version that are not in the sample are
      kept (no human work is thrown away), unjudged ones are dropped;
    - rows of other models or prompt versions are kept as they are.
    """
    groups = {(r.model, r.prompt_version) for r in sample}
    old = {_key(r): r for r in existing}
    merged = []
    for s in sample:
        e = old.get(_key(s))
        if (
            e is not None
            and e.consistent
            and (e.summary, e.input_hash) == (s.summary, s.input_hash)
        ):
            s = e
        merged.append(s)
    taken = {_key(r) for r in sample}
    merged += [
        r
        for r in existing
        if _key(r) not in taken and (r.consistent or (r.model, r.prompt_version) not in groups)
    ]
    return sorted(merged, key=_row_order)


MAX_FAILURES = 10


def _is_stale(
    row: FactCheckRow,
    items: dict[str, ItemRow],
    cached: dict[tuple[str, str, str, str], ModelOutput],
    cached_runs: set[tuple[str, str]],
) -> bool:
    """A judgment about a text that is no longer the current one: the item's frozen input
    changed, or the cache of that model and prompt version has another (or no) summary."""
    it = items.get(row.item_id)
    if it is None or row.input_hash != current_hash(it, row.model, row.prompt_version):
        return True
    if (row.model, row.prompt_version) not in cached_runs:
        return False  # cache not committed (e.g. the fake model): the CSV holds the text
    o = cached.get(_key(row))
    return o is None or o.abstained or (o.value, o.input_hash) != (row.summary, row.input_hash)


def _counts(rows: Sequence[FactCheckRow]) -> dict[str, int]:
    return {
        "n_checked": sum(bool(r.consistent) for r in rows),
        "n_consistent": sum(r.consistent == "yes" for r in rows),
    }


def factcheck_report(
    rows: Sequence[FactCheckRow], items: Sequence[ItemRow], outputs: Iterable[ModelOutput]
) -> dict[str, Any]:
    """The `t6_factcheck` block of latest.json: one run per (model, prompt version, split)."""
    by_id = {i.item_id: i for i in items}
    out = list(outputs)
    cached = {(o.model, o.prompt_version, o.item_id, o.task): o for o in out}
    cached_runs = {(o.model, o.prompt_version) for o in out}
    groups: dict[tuple[str, str, str], list[FactCheckRow]] = defaultdict(list)
    for r in rows:
        groups[(r.model, r.prompt_version, r.split)].append(r)
    runs = []
    for (model, prompt_version, split), group in sorted(groups.items()):
        current = [r for r in group if not _is_stale(r, by_id, cached, cached_runs)]
        checked = [r for r in current if r.consistent]
        flags = ["1" if r.consistent == "yes" else "0" for r in checked]
        counts = _counts(current)
        runs.append(
            {
                "model": model,
                "prompt_version": prompt_version,
                "split": split,
                "n_sampled": len(current),
                **counts,
                "consistency_rate": (
                    counts["n_consistent"] / counts["n_checked"] if checked else None
                ),
                "consistency_rate_ci95": metrics.bootstrap_ci(
                    ["1"] * len(flags), flags, metrics.accuracy, seed=metrics.BOOTSTRAP_SEED
                ),
                "n_stale": len(group) - len(current),
                "by_locale": {
                    locale: _counts([r for r in current if r.locale == locale])
                    for locale in sorted({r.locale for r in current})
                },
                "by_source": {
                    source: _counts([r for r in current if r.source == source])
                    for source in sorted({r.source for r in current})
                },
                "failures": [
                    {
                        "item_id": r.item_id,
                        "source": r.source,
                        "locale": r.locale,
                        "summary": r.summary,
                        "problem": r.problem,
                    }
                    for r in checked
                    if r.consistent == "no"
                ][:MAX_FAILURES],
            }
        )
    return {"file": f"eval/{FACTCHECK_FILE}", "sample_size": SAMPLE_SIZE, "runs": runs}


FACTCHECK_COLUMNS = tuple(f.name for f in fields(FactCheckRow))
JUDGMENTS = ("yes", "no", "")


class FactCheckError(ValueError):
    """A fact-check file that does not follow the format."""


def read_factcheck(path: Path) -> list[FactCheckRow]:
    """The rows of eval/factcheck/t6.csv (empty when the file does not exist)."""
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != FACTCHECK_COLUMNS:
            raise FactCheckError(
                f"{path.name}: expected the columns {', '.join(FACTCHECK_COLUMNS)}"
            )
        for r in reader:
            where = f"{path.name}:{reader.line_num}"
            if r["consistent"].strip() not in JUDGMENTS:
                raise FactCheckError(f"{where}: consistent must be yes, no or empty")
            try:
                snapshot = json.loads(r["input"])
            except json.JSONDecodeError as exc:
                raise FactCheckError(f"{where}: input is not JSON ({exc.msg})") from exc
            values: dict[str, Any] = dict(r)
            values |= {"input": snapshot, "consistent": r["consistent"].strip()}
            rows.append(FactCheckRow(**values))
    return rows


def next_unjudged(rows: Sequence[FactCheckRow]) -> FactCheckRow | None:
    return next((r for r in rows if not r.consistent), None)


def record_judgment(
    path: Path,
    row: FactCheckRow,
    *,
    consistent: str,
    problem: str,
    checker: str,
    now: datetime,
) -> None:
    """Write the owner's judgment of one row (eval/factcheck_app.py). A "no" needs a note
    saying what is not supported by the source."""
    if consistent not in ("yes", "no"):
        raise ValueError("consistent must be yes or no")
    if consistent == "no" and not problem.strip():
        raise ValueError("say what the problem is (which statement the source does not support)")
    judged = replace(
        row,
        consistent=consistent,
        problem=problem.strip(),
        checker=checker,
        checked_at=now.isoformat(timespec="seconds"),
    )
    write_factcheck(path, [judged if _key(r) == _key(row) else r for r in read_factcheck(path)])


def write_factcheck(path: Path, rows: Iterable[FactCheckRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(FACTCHECK_COLUMNS)
        for r in rows:
            values = asdict(r) | {"input": json.dumps(r.input, ensure_ascii=False)}
            writer.writerow([values[c] for c in FACTCHECK_COLUMNS])
