"""The regression gate of eval.yml (ticket 19).

Compares the T1 dev macro-F1 of a pull request (head: latest.json after `make eval-refresh`
and `make eval` on the PR's checkout) with the latest.json committed on `main` (base).

Rule:
- Only model runs (`kind = "model"`) of the task and split are gated; baselines are shown
  for information. Each side uses, per model, its run with the newest prompt version (a PR
  that adds `v2` still has main's `v1` cache, which `make eval` scores too).
- A model is gated when both sides have a number for it. It fails when
  main - PR > max_drop (overall macro-F1 point estimates; the bootstrap intervals are shown
  but not used: on 100 dev items they are about ±0.1 wide and would never fail).
- Everything else passes with a notice: no baseline file, no Labels on the split, a run
  with n = 0 (macro-F1 null), a model on one side only.
- A synthetic report (example.json) is refused.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Row:
    model: str
    kind: str
    base_prompt_version: str | None
    head_prompt_version: str | None
    base_macro_f1: float | None
    head_macro_f1: float | None
    base_n: int | None
    head_n: int | None
    head_ci95: Sequence[float] | None
    drop: float | None
    gated: bool
    regressed: bool


@dataclass(frozen=True)
class GateResult:
    task: str
    split: str
    max_drop: float
    rows: tuple[Row, ...]
    notices: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return not any(r.regressed for r in self.rows)


def _version_key(version: str) -> tuple[int, str]:
    match = re.fullmatch(r"v(\d+)", version)
    return (int(match.group(1)), "") if match else (-1, version)


def _newest_runs(
    report: Mapping[str, Any] | None, task: str, split: str
) -> dict[str, Mapping[str, Any]]:
    """The run of each model (and baseline) with its newest prompt version."""
    newest: dict[str, Mapping[str, Any]] = {}
    for run in (report or {}).get("runs", []):
        if run.get("task") != task or run.get("split") != split:
            continue
        current = newest.get(run["model"])
        if current is None or _version_key(run["prompt_version"]) > _version_key(
            current["prompt_version"]
        ):
            newest[run["model"]] = run
    return newest


def _not_gated_reason(
    model: str, base: Mapping[str, Any] | None, head: Mapping[str, Any] | None, split: str
) -> str:
    if head is None:
        return f"{model}: on main but not in this report; not gated"
    if base is None:
        return f"{model}: new (not on main); not gated"
    side = "this report" if head["overall"]["macro_f1"] is None else "main"
    return f"{model}: no macro-F1 on {split} in {side} (n = 0); not gated"


def compare_reports(
    base: Mapping[str, Any] | None,
    head: Mapping[str, Any],
    *,
    task: str = "hazard_category",
    split: str = "dev",
    max_drop: float = 0.02,
) -> GateResult:
    """Gate head against base (None: main has no latest.json)."""
    if any(r is not None and r.get("synthetic") for r in (base, head)):
        raise ValueError("a synthetic report (example.json) cannot be gated")
    notices = []
    if base is None:
        notices.append("no baseline: main has no committed latest.json; nothing to compare")
    if head.get("label_status", {}).get(split, {}).get("labelled", 0) == 0:
        notices.append(f"no Labels on {split} yet: every run is skipped, nothing to gate")
    base_runs = _newest_runs(base, task, split)
    head_runs = _newest_runs(head, task, split)
    rows = []
    for model in sorted(
        base_runs.keys() | head_runs.keys(),
        key=lambda m: ((base_runs.get(m) or head_runs[m]).get("kind") != "model", m),
    ):
        b, h = base_runs.get(model), head_runs.get(model)
        kind = (h or b or {}).get("kind", "model")
        b_f1 = b["overall"]["macro_f1"] if b else None
        h_f1 = h["overall"]["macro_f1"] if h else None
        gated = kind == "model" and b_f1 is not None and h_f1 is not None
        if kind == "model" and not gated and base is not None:
            notices.append(_not_gated_reason(model, b, h, split))
        # Rounding removes binary floating-point noise (0.7002 - 0.6802 =
        # 0.020000000000000018), so exactly 2 points is "not more than 2".
        drop = round(b_f1 - h_f1, 9) if b_f1 is not None and h_f1 is not None else None
        rows.append(
            Row(
                model=model,
                kind=kind,
                base_prompt_version=b["prompt_version"] if b else None,
                head_prompt_version=h["prompt_version"] if h else None,
                base_macro_f1=b_f1,
                head_macro_f1=h_f1,
                base_n=b["overall"]["n"] if b else None,
                head_n=h["overall"]["n"] if h else None,
                head_ci95=h["overall"].get("macro_f1_ci95") if h else None,
                drop=drop,
                gated=gated,
                regressed=gated and drop is not None and drop > max_drop,
            )
        )
    return GateResult(task, split, max_drop, tuple(rows), tuple(notices))


_DASH = "\N{EN DASH}"


def _score(value: float | None, prompt_version: str | None) -> str:
    if prompt_version is None:
        return _DASH
    return f"{_DASH if value is None else f'{value:.3f}'} ({prompt_version})"


def _row(row: Row) -> str:
    name = row.model if row.kind == "model" else f"{row.model} ({row.kind})"
    change = _DASH if row.drop is None else f"{-row.drop * 100:+.1f} pt"
    ci = row.head_ci95
    interval = f"{ci[0]:.3f}{_DASH}{ci[1]:.3f}" if ci else _DASH
    n = " \N{RIGHTWARDS ARROW} ".join(
        _DASH if v is None else str(v) for v in (row.base_n, row.head_n)
    )
    gate = "**regression**" if row.regressed else "ok" if row.gated else "not gated"
    cells = [
        name,
        _score(row.base_macro_f1, row.base_prompt_version),
        _score(row.head_macro_f1, row.head_prompt_version),
        change,
        interval,
        n,
        gate,
    ]
    return "| " + " | ".join(cells) + " |"


def render_markdown(result: GateResult) -> str:
    """The job summary ($GITHUB_STEP_SUMMARY) of one gate."""
    points = f"{result.max_drop * 100:.1f} points"
    lines = [
        f"### Eval gate: T1 `{result.task}` macro-F1 on {result.split}",
        "",
    ]
    regressed = [r.model for r in result.rows if r.regressed]
    if regressed:
        lines.append(f"**Failed**: {', '.join(regressed)} dropped more than {points} below main.")
    elif any(r.gated for r in result.rows):
        lines.append(f"**Passed**: no model dropped more than {points} below main.")
    else:
        lines.append("**Passed**: nothing to compare (see the notices).")
    if result.rows:
        lines += [
            "",
            "| Model | main | this PR | Change | 95% CI (PR) | n (main \N{RIGHTWARDS ARROW} PR)"
            " | Gate |",
            "|---|---|---|---|---|---|---|",
            *(_row(r) for r in result.rows),
        ]
    lines += [
        "",
        "The gate compares point estimates of model runs present on both sides (newest prompt"
        " version each); baselines and the intervals are for information.",
    ]
    if result.notices:
        lines += ["", *(f"- {n}" for n in result.notices)]
    return "\n".join(lines) + "\n"
