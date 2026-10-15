"""The sampling frame read from parsed Notifications (fixtures of all three Sources)."""

from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from openfoodalerts.db.connection import Connection
from openfoodalerts.eval.frame import FrameConfig, load_frame
from openfoodalerts.eval.labelset import default_taxonomy_path, load_taxonomy
from openfoodalerts.eval.sampling import Candidate
from openfoodalerts.fixtures import load_fixtures

pytestmark = pytest.mark.db
FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.fixture
def loaded(db: Connection) -> Connection:
    files = sorted((FIXTURES / "openfda").glob("*.json"))
    files = [f for f in files if f.name != "not_found.json"]
    files += sorted((FIXTURES / "rasff" / "details").glob("*.json"))
    files += sorted((FIXTURES / "nvwa" / "detail").glob("*.html"))
    load_fixtures(db, files)
    return db


def frame(conn: Connection, **kwargs: object) -> dict[str, Candidate]:
    taxonomy = load_taxonomy(default_taxonomy_path())
    config = FrameConfig(**kwargs)  # type: ignore[arg-type]
    return {f"{c.source}:{c.source_key}": c for c in load_frame(conn, taxonomy, config)}


def test_nvwa_candidates_are_rule_food_warnings_only(loaded: Connection) -> None:
    nvwa = {k: c for k, c in frame(loaded).items() if c.source == "nvwa"}
    types = loaded.execute(
        "SELECT n.source_key, n.product_type FROM notifications n"
        " JOIN sources s ON s.id = n.source_id WHERE s.code = 'nvwa'"
    ).fetchall()
    food = {f"nvwa:{r['source_key']}" for r in types if r["product_type"] == "food"}
    assert set(nvwa) == food
    assert nvwa  # the fixtures have food warnings
    pokebowl = next(c for k, c in nvwa.items() if "pokebowl" in k)
    assert pokebowl.group == "allergens"
    assert set(pokebowl.snapshot) == {"title", "summary", "products"}


def test_fda_candidates_cluster_by_recall_event(loaded: Connection) -> None:
    fda = [c for c in frame(loaded).values() if c.source == "openfda"]
    assert fda
    assert all(c.cluster for c in fda)
    assert all(set(c.snapshot) == {"product_description", "reason_for_recall"} for c in fda)


def test_rasff_candidates_carry_official_categories_and_need_a_hazard(loaded: Connection) -> None:
    rasff = {c.source_key: c for c in frame(loaded).values() if c.source == "rasff"}
    with_hazard = loaded.execute(
        "SELECT DISTINCT n.source_key FROM notifications n"
        " JOIN sources s ON s.id = n.source_id"
        " JOIN notification_hazards h ON h.notification_id = n.id AND h.provenance = 'official'"
        " WHERE s.code = 'rasff' AND n.product_type IN ('food', 'feed', 'food contact material')"
        " AND n.published_at >= '2020-01-01'"
    ).fetchall()
    assert set(rasff) == {r["source_key"] for r in with_hazard}
    assert all(c.official_categories for c in rasff.values())
    assert all(set(c.snapshot) == {"subject"} for c in rasff.values())
    # 2026.9489: glycidyl esters, an industrial contaminant
    assert rasff["2026.9489"].group == "industrial contaminants"
    assert rasff["2026.9489"].official_categories == ("industrial contaminants",)


def test_the_frame_ends_at_the_cutoff(loaded: Connection) -> None:
    everything = frame(loaded, end=date(2100, 1, 1))
    early = frame(loaded, end=date(2026, 10, 1))
    assert len(early) < len(everything)
    assert all(
        c.published_on is not None and c.published_on < date(2026, 10, 1) for c in early.values()
    )


def test_groups_are_t1_labels_or_none(loaded: Connection) -> None:
    labels = set(load_taxonomy(default_taxonomy_path()).labels)
    groups = Counter(c.group for c in frame(loaded).values())
    assert set(groups) - {None} <= labels
