"""Harness results into the database (spec §4.1): `eval_runs` and the `eval_labels` mirror.

eval/labels.csv stays the authoritative, published copy; `eval_labels` is rebuilt from it
on every `make eval` that reaches a database (only for items present in `eval_items`,
i.e. a database where `ofa eval-sample` ran).
"""

from collections.abc import Iterable, Mapping
from typing import Any

from psycopg.types.json import Jsonb

from openfoodalerts.db.connection import Connection
from openfoodalerts.eval.files import TASKS

_RUN_FIELDS = ("kind", "schema_version", "by_source", "overall", "per_class")


def store_runs(conn: Connection, report: Mapping[str, Any], split: str) -> int:
    """One eval_runs row per run of `split` in the report; returns the number written."""
    runs = [r for r in report["runs"] if r["split"] == split]
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO eval_runs (git_sha, model, prompt_version, taxonomy_version, split, task,
                                   metrics, confusion_matrix)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    report["git_sha"],
                    r["model"],
                    r["prompt_version"],
                    str(r["taxonomy_version"]),
                    r["split"],
                    r["task"],
                    Jsonb({k: r[k] for k in _RUN_FIELDS if k in r}),
                    Jsonb(r["confusion_matrix"]) if "confusion_matrix" in r else None,
                )
                for r in runs
            ],
        )
    conn.commit()
    return len(runs)


def sync_labels(conn: Connection, labels: Iterable[Mapping[str, str]]) -> int:
    """Replace eval_labels with the CSV's Labels; returns the number of Label rows."""
    latest: dict[tuple[str, str, str], Mapping[str, str]] = {}
    for row in labels:
        latest[(row["item_id"], row["annotator"], row["guideline_version"])] = row
    known = {r["id"] for r in conn.execute("SELECT id FROM eval_items").fetchall()}
    values = [
        (item_id, task, row[task].strip(), annotator, version, row["labelled_at"])
        for (item_id, annotator, version), row in latest.items()
        if item_id in known
        for task in TASKS
        if (row.get(task) or "").strip()
    ]
    conn.execute("DELETE FROM eval_labels")
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO eval_labels (eval_item_id, task, value, annotator, guideline_version,
                                     labelled_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            values,
        )
    conn.commit()
    return len(values)
