"""The human factual-consistency check of T6 summaries (spec §7.2): a reproducible sample
of cached summaries, the owner's judgments in eval/factcheck/t6.csv, and the
`t6_factcheck` block of latest.json."""

import json
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openfoodalerts.classify.input_hash import input_hash
from openfoodalerts.eval.cache import ModelOutput, write_outputs
from openfoodalerts.eval.factcheck import (
    FACTCHECK_COLUMNS,
    FactCheckError,
    FactCheckRow,
    factcheck_report,
    merge_sample,
    next_unjudged,
    read_factcheck,
    record_judgment,
    sample_factcheck,
    write_factcheck,
)
from openfoodalerts.eval.files import ItemRow, read_items
from tests.unit.test_eval_run import _run, eval_dir  # noqa: F401  (fixture)

NOW = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)


def item(item_id: str, source: str, split: str = "dev") -> ItemRow:
    snapshot = (
        {"title": f"Waarschuwing {item_id}", "summary": "Bevat glas.", "products": ""}
        if source == "nvwa"
        else {"product_description": f"Cookies {item_id}", "reason_for_recall": "Peanut."}
    )
    return ItemRow(item_id, split, source, item_id, "", "", "", False, False, (), snapshot)


ITEMS = [item(f"nv-{n}", "nvwa") for n in range(30)] + [
    item(f"fd-{n}", "openfda") for n in range(30)
]
ITEMS += [item("nv-test", "nvwa", "test"), item("ra-1", "rasff")]


def output(it: ItemRow, task: str, *, abstained: bool = False, stale: bool = False) -> ModelOutput:
    snapshot = {**it.input, "title": "changed"} if stale else it.input
    return ModelOutput(
        item_id=it.item_id,
        task=task,
        value=None if abstained else f"Summary of {it.item_id} ({task}).",
        confidence=None if abstained else "high",
        abstained=abstained,
        evidence_span=None,
        input_hash=input_hash(snapshot, prompt_version="v1", model="m", taxonomy_version=""),
        model="m",
        prompt_version="v1",
        schema_version="1",
        taxonomy_version="",
        created_at="2026-10-26T08:00:00+00:00",
    )


def outputs() -> list[ModelOutput]:
    out = []
    for it in ITEMS:
        if it.source == "rasff":
            continue
        tasks = ("summary_en", "summary_nl") + (("summary_zh",) if it.source == "nvwa" else ())
        out += [output(it, task) for task in tasks]
        out.append(ModelOutput(**{**output(it, "summary_en").__dict__, "task": "hazard_category"}))
    return out


def test_the_sample_is_reproducible_and_spread_over_sources_and_languages() -> None:
    rows = sample_factcheck(ITEMS, outputs(), model="m", prompt_version="v1", split="dev")
    assert len(rows) == 50
    assert rows == sample_factcheck(
        ITEMS, list(reversed(outputs())), model="m", prompt_version="v1", split="dev"
    )
    # five strata (NVWA en/nl/zh, FDA en/nl), ten each
    assert Counter((r.source, r.locale) for r in rows) == {
        ("nvwa", "en"): 10,
        ("nvwa", "nl"): 10,
        ("nvwa", "zh"): 10,
        ("openfda", "en"): 10,
        ("openfda", "nl"): 10,
    }
    assert all(r.split == "dev" and r.consistent == "" for r in rows)
    first = next(r for r in rows if r.item_id.startswith("nv-"))
    assert first.summary == f"Summary of {first.item_id} ({first.task})."
    assert first.input == next(i for i in ITEMS if i.item_id == first.item_id).input
    other_seed = sample_factcheck(
        ITEMS, outputs(), model="m", prompt_version="v1", split="dev", seed=1
    )
    assert {(r.item_id, r.task) for r in other_seed} != {(r.item_id, r.task) for r in rows}


def test_only_current_answered_summaries_of_the_split_are_sampled() -> None:
    nv, fd = ITEMS[0], ITEMS[30]
    cached = [
        output(nv, "summary_en"),
        output(nv, "summary_nl", abstained=True),
        output(fd, "summary_en", stale=True),
        output(ITEMS[60], "summary_en"),  # a test item
    ]
    rows = sample_factcheck(ITEMS, cached, model="m", prompt_version="v1", split="dev")
    assert [(r.item_id, r.task) for r in rows] == [(nv.item_id, "summary_en")]
    assert sample_factcheck(ITEMS, cached, model="other", prompt_version="v1", split="dev") == []


def sample(n: int = 6) -> list[FactCheckRow]:
    return sample_factcheck(ITEMS, outputs(), model="m", prompt_version="v1", split="dev", n=n)


def judged(row: FactCheckRow, consistent: str = "yes", problem: str = "") -> FactCheckRow:
    return replace(
        row, consistent=consistent, problem=problem, checker="A", checked_at="2026-10-27"
    )


def test_the_file_round_trips_and_rejects_unknown_judgments(tmp_path: Path) -> None:
    path = tmp_path / "factcheck" / "t6.csv"
    assert read_factcheck(path) == []
    rows = [judged(sample()[0], "no", 'Adds "2026", a date the source lacks.'), *sample()[1:]]
    write_factcheck(path, rows)
    assert read_factcheck(path) == rows
    assert path.read_text(encoding="utf-8").splitlines()[0] == ",".join(FACTCHECK_COLUMNS)
    path.write_text(
        path.read_text(encoding="utf-8").replace(",no,", ",maybe,", 1), encoding="utf-8"
    )
    with pytest.raises(FactCheckError, match=r"t6.csv:2"):
        read_factcheck(path)


def test_the_report_counts_judgments_per_language_and_lists_failures() -> None:
    rows = sample(n=7)
    problem = "Says the product was sold at Jumbo; the source does not."
    judgments = ["yes", "yes", "no", "yes", "yes", ""]
    rows = [
        judged(r, j, problem if j == "no" else "") if j else r
        for r, j in zip(rows, judgments, strict=False)
    ] + [
        # judged against an input that has changed since (items.csv was resampled)
        judged(replace(rows[6], input_hash="0" * 64))
    ]
    block = factcheck_report(rows, ITEMS, outputs())
    [run] = block["runs"]
    failed = rows[2]
    assert {
        k: run[k] for k in run if k not in ("by_locale", "by_source", "consistency_rate_ci95")
    } == {
        "model": "m",
        "prompt_version": "v1",
        "split": "dev",
        "n_sampled": 6,
        "n_checked": 5,
        "n_consistent": 4,
        "consistency_rate": 0.8,
        "n_stale": 1,
        "failures": [
            {
                "item_id": failed.item_id,
                "source": failed.source,
                "locale": failed.locale,
                "summary": failed.summary,
                "problem": problem,
            }
        ],
    }
    ci = run["consistency_rate_ci95"]
    assert ci is not None and ci[0] <= 0.8 <= ci[1]
    assert sum(b["n_checked"] for b in run["by_locale"].values()) == 5
    assert sum(b["n_consistent"] for b in run["by_source"].values()) == 4
    assert block["sample_size"] == 50


def test_a_judgment_of_a_summary_the_cache_no_longer_has_is_stale() -> None:
    row = judged(sample(n=1)[0])
    cached = [replace(o, value="A newer summary.") for o in outputs()]
    [run] = factcheck_report([row], ITEMS, cached)["runs"]
    assert (run["n_checked"], run["n_stale"], run["consistency_rate"]) == (0, 1, None)
    # without a cache (not committed, e.g. the fake model) the CSV's text is what was judged
    [run] = factcheck_report([row], ITEMS, [])["runs"]
    assert (run["n_checked"], run["n_stale"]) == (1, 0)
    assert factcheck_report([], ITEMS, [])["runs"] == []


def test_make_eval_reports_the_factcheck_and_does_not_score_summaries(
    eval_dir: Path,  # noqa: F811
) -> None:
    report, _ = _run(eval_dir)
    assert report["t6_factcheck"]["runs"] == []
    [it] = [i for i in read_items(eval_dir / "items.csv") if i.item_id == "fd-00000001"]
    summary = "Cookies are recalled because of undeclared milk."
    cached = replace(
        outputs()[0],
        item_id=it.item_id,
        value=summary,
        input_hash=input_hash(it.input, prompt_version="v1", model="m", taxonomy_version=""),
    )
    write_outputs(eval_dir / "cache", [cached])
    [row] = sample_factcheck([it], [cached], model="m", prompt_version="v1", split="dev")
    write_factcheck(eval_dir / "factcheck" / "t6.csv", [judged(row)])
    report, _ = _run(eval_dir)
    [run] = report["t6_factcheck"]["runs"]
    assert (run["model"], run["n_checked"], run["n_consistent"]) == ("m", 1, 1)
    assert all(not r["task"].startswith("summary_") for r in report["runs"] + report["skipped"])
    written = json.loads((eval_dir / "results" / "latest.json").read_text(encoding="utf-8"))
    assert written["t6_factcheck"] == report["t6_factcheck"]


def test_judgments_are_recorded_one_row_at_a_time(tmp_path: Path) -> None:
    path = tmp_path / "t6.csv"
    rows = sample(n=3)
    write_factcheck(path, rows)
    assert next_unjudged(read_factcheck(path)) == rows[0]
    record_judgment(path, rows[0], consistent="no", problem="Adds a shop.", checker="A", now=NOW)
    record_judgment(path, rows[1], consistent="yes", problem="", checker="A", now=NOW)
    got = read_factcheck(path)
    assert (got[0].consistent, got[0].problem, got[0].checker) == ("no", "Adds a shop.", "A")
    assert got[0].checked_at == "2026-10-27T09:00:00+00:00"
    assert next_unjudged(got) == rows[2]
    with pytest.raises(ValueError, match="problem"):
        record_judgment(path, rows[2], consistent="no", problem=" ", checker="A", now=NOW)
    with pytest.raises(ValueError, match="yes or no"):
        record_judgment(path, rows[2], consistent="", problem="", checker="A", now=NOW)
    record_judgment(path, rows[2], consistent="yes", problem="", checker="A", now=NOW)
    assert next_unjudged(read_factcheck(path)) is None


def test_a_new_sample_keeps_judgments_of_the_same_summary() -> None:
    old = sample()
    kept, changed, dropped_unchecked = old[0], old[1], old[2]
    outside = replace(judged(old[3]), item_id="nv-99")  # judged, no longer in the sample
    other_model = replace(old[4], model="other")  # unjudged, another model's sample
    existing = [
        judged(kept),
        judged(replace(changed, summary="An older summary.")),
        dropped_unchecked,
        outside,
        other_model,
    ]
    merged = merge_sample(existing, old)
    by_key = {(r.model, r.item_id, r.task): r for r in merged}
    assert by_key[("m", kept.item_id, kept.task)].consistent == "yes"
    # the summary changed: the judgment was about another text
    assert by_key[("m", changed.item_id, changed.task)].consistent == ""
    assert by_key[("m", changed.item_id, changed.task)].summary == changed.summary
    assert by_key[("m", "nv-99", outside.task)] == outside
    assert by_key[("other", other_model.item_id, other_model.task)] == other_model
    assert len(merged) == len(old) + 2
