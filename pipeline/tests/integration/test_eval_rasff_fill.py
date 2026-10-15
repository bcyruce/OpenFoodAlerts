"""`eval-fetch-rasff` against a fake RASFF backend serving the detail fixtures."""

from datetime import date

import httpx
import pytest

from openfoodalerts.db.connection import Connection
from openfoodalerts.eval.labelset import default_taxonomy_path, load_taxonomy
from openfoodalerts.eval.rasff_fill import fill_rasff
from tests.rasff_fake import FakeRasff

pytestmark = pytest.mark.db


def archived(conn: Connection, kind: str) -> list[str]:
    rows = conn.execute(
        "SELECT source_key FROM raw_records WHERE kind = %s ORDER BY id", (kind,)
    ).fetchall()
    return [r["source_key"] for r in rows]


def run(conn: Connection, fake: FakeRasff, plan: dict[str, int]) -> dict[str, int]:
    taxonomy = load_taxonomy(default_taxonomy_path())
    with fake.client() as client:
        result = fill_rasff(
            conn,
            client,
            plan,
            taxonomy,
            seed=7,
            since=date(2020, 1, 1),
            until=date(2026, 10, 25),
        )
    return result.fetched


def test_lists_by_the_label_categories_and_fetches_the_planned_details(db: Connection) -> None:
    fake = FakeRasff()
    assert run(db, fake, {"GMO / novel food": 2}) == {"GMO / novel food": 2}
    [body] = fake.list_requests
    assert sorted(body["hazardCategory"]) == [21806, 26580, 26581]
    assert body["notificationType"] == [283, 282, 281]
    assert body["ecValidDateFrom"] == "01-01-2020 00:00:00"
    assert body["ecValidDateTo"] == "25-10-2026 00:00:00"
    assert body["parameters"]["itemsPerPage"] == 99
    assert len(archived(db, "detail")) == 2
    assert len(archived(db, "list")) == 1


class BrokenDetails(FakeRasff):
    """Some old RASFF details answer HTTP 500 every time."""

    def __init__(self, broken: set[int]) -> None:
        super().__init__()
        self.broken = broken

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            notif_id = int(request.url.path.rstrip("/").split("/")[-2])
            if notif_id in self.broken:
                self.detail_requests.append(notif_id)
                return httpx.Response(500)
        return super().handler(request)


def test_a_detail_that_keeps_failing_is_skipped_for_the_next_candidate(db: Connection) -> None:
    probe = FakeRasff()
    run(db, probe, {"allergens": 1})
    first_choice = probe.detail_requests[0]
    db.execute("TRUNCATE raw_records CASCADE")
    db.commit()
    fake = BrokenDetails({first_choice})
    assert run(db, fake, {"allergens": 1}) == {"allergens": 1}
    assert fake.detail_requests[0] == first_choice
    assert len(set(fake.detail_requests)) == 2
    assert len(archived(db, "detail")) == 1


def test_a_second_run_skips_archived_details(db: Connection) -> None:
    fake = FakeRasff()
    run(db, fake, {"allergens": 3})
    first = list(fake.detail_requests)
    run(db, fake, {"allergens": 3})
    second = fake.detail_requests[len(first) :]
    assert len(second) == 3
    assert not set(first) & set(second)
    assert len(set(archived(db, "detail"))) == 6
