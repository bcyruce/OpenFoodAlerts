"""Harness output into the database: eval_runs rows and the eval_labels mirror."""

from pathlib import Path
from typing import Any

import pytest

from openfoodalerts.db.connection import Connection
from openfoodalerts.eval.files import read_items
from openfoodalerts.eval.job import run_sampling
from openfoodalerts.eval.labelset import default_taxonomy_path
from openfoodalerts.eval.sampling import SamplingConfig
from openfoodalerts.eval.store import store_runs, sync_labels
from openfoodalerts.fixtures import load_fixtures

pytestmark = pytest.mark.db
FIXTURES = Path(__file__).parents[1] / "fixtures"


def _run(model: str, split: str, task: str = "hazard_category") -> dict[str, Any]:
    return {
        "model": model,
        "prompt_version": "v1",
        "kind": "model",
        "split": split,
        "task": task,
        "schema_version": "1",
        "taxonomy_version": 1,
        "by_source": {"nvwa": {"n": 3}},
        "overall": {"n": 3, "macro_f1": 0.5},
        "per_class": {"allergens": {"precision": 1.0, "recall": 0.5, "f1": 0.66, "support": 2}},
        "confusion_matrix": {"labels": ["allergens", "abstain"], "matrix": [[1, 1], [0, 0]]},
    }


def test_one_eval_runs_row_per_run_of_the_scored_split(db: Connection) -> None:
    report = {
        "git_sha": "abc123",
        "taxonomy_version": 1,
        "runs": [_run("m", "dev"), _run("m", "dev", "product_type"), _run("m", "test")],
    }
    assert store_runs(db, report, "dev") == 2
    rows = db.execute(
        "SELECT git_sha, model, prompt_version, taxonomy_version, split, task, metrics,"
        " confusion_matrix FROM eval_runs ORDER BY id"
    ).fetchall()
    assert [(r["split"], r["task"]) for r in rows] == [
        ("dev", "hazard_category"),
        ("dev", "product_type"),
    ]
    first = rows[0]
    assert (first["git_sha"], first["model"], first["prompt_version"]) == ("abc123", "m", "v1")
    assert first["taxonomy_version"] == "1"
    assert first["metrics"]["overall"]["macro_f1"] == 0.5
    assert first["metrics"]["by_source"]["nvwa"]["n"] == 3
    assert first["metrics"]["kind"] == "model"
    assert first["confusion_matrix"]["matrix"] == [[1, 1], [0, 0]]


def test_labels_are_mirrored_into_eval_labels_for_known_items(
    db: Connection, tmp_path: Path
) -> None:
    files = sorted((FIXTURES / "nvwa" / "detail").glob("*.html"))
    load_fixtures(db, files)
    run_sampling(
        db,
        taxonomy_path=default_taxonomy_path(),
        eval_dir=tmp_path,
        config=SamplingConfig(quotas={"nvwa": 2, "openfda": 0, "rasff": 0}, min_per_label=0),
    )
    first = read_items(tmp_path / "items.csv")[0].item_id
    base = {
        "item_id": first,
        "annotator": "A",
        "guideline_version": "v1",
        "hazard_category": "allergens",
        "product_category": "unsure",
        "hazard": "melk",
        "origin_country": "unknown",
        "product_type": "food",
        "note": "",
        "labelled_at": "2026-10-26T08:00:00+00:00",
    }
    corrected = base | {
        "hazard_category": "foreign bodies",
        "product_type": "",  # blank values are not Labels
        "labelled_at": "2026-10-26T09:00:00+00:00",
    }
    labels = [base, base | {"item_id": "nv-00000000"}, corrected]  # nv-00000000: unknown item
    assert sync_labels(db, labels[:1]) == 5
    # the CSV is authoritative: the mirror is rebuilt from the last row per
    # item / annotator / guideline version
    assert sync_labels(db, labels) == 4
    rows = db.execute(
        "SELECT task, value, labelled_at FROM eval_labels WHERE eval_item_id = %s ORDER BY task",
        (first,),
    ).fetchall()
    assert {r["task"]: r["value"] for r in rows} == {
        "hazard": "melk",
        "hazard_category": "foreign bodies",
        "origin_country": "unknown",
        "product_category": "unsure",
    }
    # idempotent
    assert sync_labels(db, labels) == 4
    assert db.execute("SELECT count(*) AS n FROM eval_labels").fetchone() == {"n": 4}
