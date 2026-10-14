"""`ofa eval-sample` / `ofa eval-exclude`: frame -> eval set -> CSVs + eval_items."""

import json
from pathlib import Path

import pytest

from openfoodalerts.db.connection import Connection
from openfoodalerts.eval.files import LABEL_COLUMNS, read_exclusions, read_items
from openfoodalerts.eval.job import EvalSetChanged, exclude_items, run_sampling
from openfoodalerts.eval.labelset import default_taxonomy_path
from openfoodalerts.eval.sampling import SamplingConfig
from openfoodalerts.fixtures import load_fixtures

pytestmark = pytest.mark.db
FIXTURES = Path(__file__).parents[1] / "fixtures"
SMALL = SamplingConfig(quotas={"nvwa": 3, "openfda": 3, "rasff": 3}, min_per_label=1)


@pytest.fixture
def loaded(db: Connection) -> Connection:
    files = [f for f in sorted((FIXTURES / "openfda").glob("*.json")) if f.name != "not_found.json"]
    files += sorted((FIXTURES / "rasff" / "details").glob("*.json"))
    files += sorted((FIXTURES / "nvwa" / "detail").glob("*.html"))
    load_fixtures(db, files)
    return db


def sample(conn: Connection, eval_dir: Path, **kwargs: object) -> None:
    run_sampling(
        conn,
        taxonomy_path=default_taxonomy_path(),
        eval_dir=eval_dir,
        config=SMALL,
        **kwargs,  # type: ignore[arg-type]
    )


def test_writes_items_labels_header_summary_and_eval_items(
    loaded: Connection, tmp_path: Path
) -> None:
    sample(loaded, tmp_path)
    items = read_items(tmp_path / "items.csv")
    assert len(items) == 9
    assert (tmp_path / "labels.csv").read_text(encoding="utf-8") == ",".join(LABEL_COLUMNS) + "\n"
    summary = json.loads((tmp_path / "sampling.json").read_text(encoding="utf-8"))
    assert summary["seed"] == SMALL.seed
    assert summary["taxonomy"]["version"] == "v1-draft"
    assert summary["taxonomy"]["path"] == "db/seed/taxonomy/v1-draft.csv"
    assert sum(summary["frame_sizes"].values()) >= 9
    rows = loaded.execute(
        "SELECT id, source_code, split, status, input_snapshot FROM eval_items ORDER BY id"
    ).fetchall()
    assert [r["id"] for r in rows] == sorted(i.item_id for i in items)
    assert {r["status"] for r in rows} == {"active"}
    by_id = {i.item_id: i for i in items}
    assert all(r["input_snapshot"] == by_id[r["id"]].input for r in rows)


def test_a_rerun_gives_byte_identical_files(loaded: Connection, tmp_path: Path) -> None:
    sample(loaded, tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    sample(loaded, tmp_path)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_exclude_replaces_the_item_and_records_it(loaded: Connection, tmp_path: Path) -> None:
    sample(loaded, tmp_path)
    first = read_items(tmp_path / "items.csv")
    gone = next(i for i in first if i.source == "nvwa")
    exclude_items(
        loaded,
        [gone.item_id],
        reason="non-food",
        taxonomy_path=default_taxonomy_path(),
        eval_dir=tmp_path,
        config=SMALL,
    )
    after = read_items(tmp_path / "items.csv")
    assert gone.item_id not in {i.item_id for i in after}
    assert len(after) == 9
    [record] = read_exclusions(tmp_path / "exclusions.csv")
    assert (record.item_id, record.reason) == (gone.item_id, "non-food")
    assert record.replaced_by in {i.item_id for i in after}
    row = loaded.execute(
        "SELECT status, replaced_by FROM eval_items WHERE id = %s", (gone.item_id,)
    ).fetchone()
    assert row == {"status": "excluded", "replaced_by": record.replaced_by}
    # replayed on the next plain run, also when the excluded item has Labels in the database
    loaded.execute(
        "INSERT INTO eval_labels (eval_item_id, task, value, annotator, guideline_version,"
        " labelled_at) VALUES (%s, 'product_type', 'non-food', 'A', 'v1', now())",
        (gone.item_id,),
    )
    loaded.commit()
    sample(loaded, tmp_path)
    assert read_items(tmp_path / "items.csv") == after
    row = loaded.execute(
        "SELECT status, replaced_by FROM eval_items WHERE id = %s", (gone.item_id,)
    ).fetchone()
    assert row == {"status": "excluded", "replaced_by": record.replaced_by}


def test_refuses_to_drop_an_item_that_already_has_labels(
    loaded: Connection, tmp_path: Path
) -> None:
    sample(loaded, tmp_path)
    labelled = read_items(tmp_path / "items.csv")[0]
    with (tmp_path / "labels.csv").open("a", encoding="utf-8", newline="") as f:
        f.write(f"{labelled.item_id},A,v1,allergens,,,,food,,2026-10-26T08:00:00+00:00\n")
    nothing = SamplingConfig(quotas={"nvwa": 0, "openfda": 0, "rasff": 0}, min_per_label=1)
    with pytest.raises(EvalSetChanged, match=labelled.item_id):
        run_sampling(
            loaded, taxonomy_path=default_taxonomy_path(), eval_dir=tmp_path, config=nothing
        )
    assert len(read_items(tmp_path / "items.csv")) == 9  # untouched
    run_sampling(
        loaded,
        taxonomy_path=default_taxonomy_path(),
        eval_dir=tmp_path,
        config=nothing,
        force=True,
    )
    assert read_items(tmp_path / "items.csv") == []
