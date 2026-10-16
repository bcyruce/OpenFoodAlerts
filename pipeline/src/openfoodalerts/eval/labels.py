"""Labels for scoring, from the append-only eval/labels.csv.

For each item and annotator the row that counts is the last one under the highest
guideline version that annotator used for that item (v10 > v9). Items relabelled under a
new guideline thus switch over one by one, and items not yet relabelled keep their older
Label. `unsure` and a blank value mean "no Label" for that task: the item is left out
of the task's metrics and counted under n_unsure / n_unlabelled. `none` (T3: no Hazard
named) and `unknown` (T4: origin not stated) are real Labels.
"""

import re
from collections.abc import Iterable, Mapping

from openfoodalerts.eval.labeling import UNSURE


def _version_key(version: str) -> tuple[int, str]:
    match = re.fullmatch(r"v?(\d+)", version.strip())
    return (int(match.group(1)), "") if match else (-1, version)


def latest_labels(rows: Iterable[Mapping[str, str]], annotator: str) -> dict[str, dict[str, str]]:
    best: dict[str, dict[str, str]] = {}
    for row in rows:
        if row["annotator"] != annotator:
            continue
        current = best.get(row["item_id"])
        if current is None or _version_key(row["guideline_version"]) >= _version_key(
            current["guideline_version"]
        ):
            best[row["item_id"]] = dict(row)
    return best


def label_value(row: Mapping[str, str] | None, task: str) -> str | None:
    if row is None:
        return None
    value = (row.get(task) or "").strip()
    return None if not value or value == UNSURE else value
