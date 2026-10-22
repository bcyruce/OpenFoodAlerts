"""`run_eval`: the committed eval files + cache -> eval/results/latest.json."""

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from openfoodalerts.classify.input_hash import input_hash
from openfoodalerts.eval.cache import ModelOutput, write_outputs
from openfoodalerts.eval.files import ITEM_COLUMNS, LABEL_COLUMNS
from openfoodalerts.eval.harness import run_eval

TAXONOMY = (
    "rasff_id,name_en,notifications_since_2020-01-01,label\n"
    "21801,pathogenic micro-organisms,6000,pathogenic micro-organisms\n"
    "21798,allergens,500,allergens\n"
    "21800,mycotoxins,400,mycotoxins\n"
)
NOW = "2026-10-26T08:00:00+00:00"
ITEMS = [
    ("fd-00000001", "dev", "openfda", "Cookies", "Undeclared milk"),
    ("fd-00000002", "dev", "openfda", "Peanut butter", "Salmonella contamination"),
    ("fd-00000003", "test", "openfda", "Figs", "Aflatoxin above limit"),
]
SILVER = [
    ("Listeria in cheese", "pathogenic micro-organisms"),
    ("Salmonella in chicken", "pathogenic micro-organisms"),
    ("Aflatoxins in figs", "mycotoxins"),
    ("Aflatoxins in nuts", "mycotoxins"),
    ("Undeclared milk in cake", "allergens"),
    ("Undeclared peanut in bars", "allergens"),
]


def _input(product: str, reason: str) -> dict[str, str]:
    return {"product_description": product, "reason_for_recall": reason}


@pytest.fixture
def eval_dir(tmp_path: Path) -> Path:
    d = tmp_path / "eval"
    d.mkdir()
    with (d / "items.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(ITEM_COLUMNS)
        for item_id, split, source, product, reason in ITEMS:
            snapshot = json.dumps(_input(product, reason))
            w.writerow(
                [item_id, split, source, item_id, "", "", "", "false", "false", "", snapshot]
            )
    with (d / "labels.csv").open("w", encoding="utf-8", newline="") as f:
        csv.writer(f, lineterminator="\n").writerow(LABEL_COLUMNS)
    with (d / "silver.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["source_key", "published_on", "label", "rasff_categories", "subject"])
        for i, (subject, label) in enumerate(SILVER):
            w.writerow([f"2026.{i}", "2026-10-22", label, label, subject])
    (tmp_path / "v1.csv").write_text(TAXONOMY, encoding="utf-8")
    return d


def _label(eval_dir: Path, item_id: str, t1: str) -> None:
    with (eval_dir / "labels.csv").open("a", encoding="utf-8", newline="") as f:
        csv.writer(f, lineterminator="\n").writerow(
            [item_id, "A", "v1", t1, "unsure", "none", "unknown", "food", "", NOW]
        )


def _cache(eval_dir: Path, item_id: str, value: str) -> None:
    product, reason = next((p, r) for i, _, _, p, r in ITEMS if i == item_id)
    write_outputs(
        eval_dir / "cache",
        [
            ModelOutput(
                item_id=item_id,
                task="hazard_category",
                value=value,
                confidence="high",
                abstained=False,
                evidence_span=None,
                input_hash=input_hash(
                    _input(product, reason),
                    prompt_version="v1",
                    model="claude-haiku-5-5",
                    taxonomy_version="1",
                ),
                model="claude-haiku-5-5",
                prompt_version="v1",
                schema_version="1",
                taxonomy_version="1",
                created_at=NOW,
            )
        ],
    )


def _run(eval_dir: Path, split: str = "dev") -> tuple[dict[str, Any], list[str]]:
    return run_eval(
        eval_dir,
        split=split,
        taxonomy_path=eval_dir.parent / "v1.csv",
        output=eval_dir / "results" / "latest.json",
        created_at=NOW,
        git_sha="abc123",
    )


def test_without_labels_both_baselines_are_skipped_and_latest_json_is_written(
    eval_dir: Path,
) -> None:
    report, notices = _run(eval_dir)
    assert notices == []
    written = json.loads((eval_dir / "results" / "latest.json").read_text(encoding="utf-8"))
    assert written == report
    assert written["runs"] == []
    assert [(s["model"], s["task"]) for s in written["skipped"]] == [
        ("baseline-keywords", "hazard_category"),
        ("baseline-tfidf-lr", "hazard_category"),
    ]


def test_cached_models_and_baselines_are_scored_and_the_other_split_is_kept(
    eval_dir: Path,
) -> None:
    for item_id, t1 in [
        ("fd-00000001", "allergens"),
        ("fd-00000002", "pathogenic micro-organisms"),
        ("fd-00000003", "mycotoxins"),
    ]:
        _label(eval_dir, item_id, t1)
    _cache(eval_dir, "fd-00000001", "allergens")
    _cache(eval_dir, "fd-00000002", "allergens")
    _cache(eval_dir, "fd-00000003", "mycotoxins")

    test_report, _ = _run(eval_dir, "test")
    assert {(r["model"], r["split"]) for r in test_report["runs"]} == {
        ("claude-haiku-5-5", "test"),
        ("baseline-keywords", "test"),
        ("baseline-tfidf-lr", "test"),
    }
    report, _ = _run(eval_dir)
    runs = {(r["model"], r["split"]): r for r in report["runs"]}
    assert len(runs) == 6  # dev runs added, test runs kept
    assert runs[("claude-haiku-5-5", "dev")]["overall"]["accuracy"] == 0.5
    assert runs[("claude-haiku-5-5", "dev")]["kind"] == "model"
    assert runs[("baseline-keywords", "dev")]["kind"] == "baseline"
    assert runs[("baseline-keywords", "dev")]["overall"]["accuracy"] == 1.0
    assert runs[("claude-haiku-5-5", "test")]["overall"]["accuracy"] == 1.0


def test_the_decisions_written_into_latest_json_survive_the_next_make_eval(
    eval_dir: Path,
) -> None:
    """ofa eval-threshold / eval-compare write `thresholds` and `model_selection`; they
    are decisions, not scores, so re-scoring keeps them."""
    report, _ = _run(eval_dir)
    decisions = {
        "thresholds": [
            {
                "model": "claude-haiku-5-5",
                "prompt_version": "v1",
                "task": "hazard_category",
                "min_confidence": "medium",
            }
        ],
        "model_selection": {"status": "pending", "selected": "claude-haiku-5-5"},
    }
    out = eval_dir / "results" / "latest.json"
    out.write_text(json.dumps(report | decisions), encoding="utf-8")
    again, _ = _run(eval_dir)
    assert again["thresholds"] == decisions["thresholds"]
    assert again["model_selection"] == decisions["model_selection"]
    assert json.loads(out.read_text(encoding="utf-8"))["thresholds"] == decisions["thresholds"]


def test_a_silver_set_with_one_label_skips_the_tfidf_baseline_with_a_notice(
    eval_dir: Path,
) -> None:
    lines = (eval_dir / "silver.csv").read_text(encoding="utf-8").splitlines()
    (eval_dir / "silver.csv").write_text("\n".join(lines[:3]) + "\n", encoding="utf-8")
    report, notices = _run(eval_dir)
    assert any("baseline-tfidf-lr" in n for n in notices)
    assert [s["model"] for s in report["skipped"]] == ["baseline-keywords"]
