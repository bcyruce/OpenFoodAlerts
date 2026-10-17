"""The README badge (ticket 25): a shields.io endpoint payload built from latest.json.

`eval/results/badge.json` is written next to latest.json by `ofa eval-run` (and by
`ofa eval-badge` from an existing report) and committed with it; the README points
shields.io at its raw GitHub URL. The badge shows the overall T1 macro-F1 on the frozen
test split of every model run (baselines are not models). With several models all are
shown: the badge does not pick the best one. The colour is a neutral blue, not a verdict.
A synthetic report (example.json) never becomes a badge.
"""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

LABEL = "T1 macro-F1 (test)"
TASK = "hazard_category"
SPLIT = "test"


def _payload(message: str, color: str) -> dict[str, Any]:
    return {"schemaVersion": 1, "label": LABEL, "message": message, "color": color}


def badge_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    if report.get("synthetic"):
        raise ValueError("a synthetic report must not become the badge")
    labelled = sum(s.get("labelled", 0) for s in report.get("label_status", {}).values())
    if labelled == 0:
        return _payload("no labels yet", "lightgrey")
    runs = [
        r
        for r in report.get("runs", [])
        if r.get("kind") == "model"
        and r.get("split") == SPLIT
        and r.get("task") == TASK
        and r.get("overall", {}).get("macro_f1") is not None
    ]
    if not runs:
        return _payload("no test run yet", "lightgrey")
    if len(runs) == 1:
        overall = runs[0]["overall"]
        ci = overall.get("macro_f1_ci95")
        interval = f" (95% CI {ci[0]:.2f}\N{EN DASH}{ci[1]:.2f})" if ci else ""
        return _payload(f"{runs[0]['model']} {overall['macro_f1']:.2f}{interval}", "blue")
    return _payload(
        " · ".join(f"{r['model']} {r['overall']['macro_f1']:.2f}" for r in runs), "blue"
    )


def write_badge(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(badge_payload(report), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
