import httpx

from openfoodalerts.sources.rasff.client import RasffClient
from openfoodalerts.taxonomy import CategoryCount, count_hazard_categories, draft_merge


def c(rasff_id: int, name: str, count: int) -> CategoryCount:
    return CategoryCount(rasff_id=rasff_id, name=name, count=count)


def labels(rows: list[CategoryCount]) -> dict[str, str]:
    return {r.name: r.label for r in draft_merge(rows)}


def test_large_categories_keep_their_name() -> None:
    assert labels([c(1, "allergens", 2500)]) == {"allergens": "allergens"}


def test_small_categories_fold_into_other() -> None:
    got = labels([c(1, "allergens", 2500), c(2, "TSEs", 29), c(3, "radiation", 30)])
    assert got == {"allergens": "allergens", "TSEs": "other", "radiation": "radiation"}


def test_gmo_and_novel_food_merge_before_the_threshold_applies() -> None:
    got = labels(
        [c(1, "GMO / novel food", 10), c(2, "novel food", 15), c(3, "genetically modified", 6)]
    )
    assert set(got.values()) == {"GMO / novel food"}


def test_merged_gmo_group_still_folds_when_small_in_total() -> None:
    got = labels([c(1, "GMO / novel food", 10), c(2, "novel food", 5)])
    assert set(got.values()) == {"other"}


def test_counts_each_category_from_the_list_total() -> None:
    seen: list[object] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = __import__("json").loads(request.content)
        seen.append(body)
        return httpx.Response(200, json={"totalElements": 7 * body["hazardCategory"][0]})

    with RasffClient.create(transport=httpx.MockTransport(handler), sleep=lambda s: None) as rc:
        counts = count_hazard_categories(rc, since="01-01-2020 00:00:00", product_types=[283])
    assert len(counts) == 30
    first = counts[0]
    assert first.count == 7 * first.rasff_id
    assert seen[0] == {
        "parameters": {"pageNumber": 1, "itemsPerPage": 1},
        "ecValidDateFrom": "01-01-2020 00:00:00",
        "hazardCategory": [first.rasff_id],
        "notificationType": [283],
    }
