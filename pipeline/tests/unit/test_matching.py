"""Which Notifications a Subscription's filters match (spec §10.1, §10.2). Shared by the
Digest and Instant email (tickets 30, 31)."""

from typing import Any

from openfoodalerts.mail.matching import (
    NotificationFacets,
    SubscriptionFilter,
    matches,
    matches_news,
)

SALMONELLA = 21801  # pathogenic micro-organisms (RASFF hazard category id)
ALLERGENS = 21798
NUTS = 18427  # nuts, nut products and seeds (RASFF product category id)


def sub(
    *, locale: str = "en", include_unclassified: bool = True, **filters: list[Any]
) -> SubscriptionFilter:
    return SubscriptionFilter.from_row(
        {
            "locale": locale,
            "filters": {
                "sources": [],
                "hazard_categories": [],
                "product_categories": [],
                "origin_countries": [],
                **filters,
            },
            "include_unclassified": include_unclassified,
        }
    )


def facets(
    *,
    source: str = "rasff",
    product_type: str | None = "food",
    notification_type: str = "alert",
    hazards: tuple[int, ...] = (),
    products: tuple[int, ...] = (),
    origins: tuple[str, ...] = (),
) -> NotificationFacets:
    return NotificationFacets(
        id=1,
        source=source,
        product_type=product_type,
        notification_type=notification_type,
        hazard_categories=frozenset(hazards),
        product_categories=frozenset(products),
        origin_countries=frozenset(origins),
    )


def test_empty_filters_match_everything_in_scope() -> None:
    assert matches(sub(), facets())
    assert matches(sub(), facets(source="nvwa", notification_type="safety warning"))


def test_only_food_feed_and_food_contact_material_are_in_scope() -> None:
    for product_type in ("food", "feed", "food contact material"):
        assert matches(sub(), facets(product_type=product_type))
    assert not matches(sub(), facets(product_type="non-food"))
    # Waiting for T5: not in scope yet.
    assert not matches(sub(), facets(product_type=None))


def test_sources_filter() -> None:
    s = sub(sources=["nvwa", "openfda"])
    assert matches(s, facets(source="nvwa"))
    assert not matches(s, facets(source="rasff"))


def test_hazard_category_matches_any_of_the_notifications_categories() -> None:
    s = sub(hazard_categories=[SALMONELLA], include_unclassified=False)
    assert matches(s, facets(hazards=(ALLERGENS, SALMONELLA)))
    assert not matches(s, facets(hazards=(ALLERGENS,)))
    assert not matches(s, facets(hazards=()))


def test_include_unclassified_matches_notifications_without_a_value_in_that_dimension() -> None:
    s = sub(hazard_categories=[SALMONELLA], origin_countries=["TR"], include_unclassified=True)
    # No hazard category at all (e.g. AI abstained): counts as a match for that dimension.
    assert matches(s, facets(hazards=(), origins=("TR",)))
    # A different category is still not a match.
    assert not matches(s, facets(hazards=(ALLERGENS,), origins=("TR",)))
    # Every set filter must hold.
    assert not matches(s, facets(hazards=(SALMONELLA,), origins=("NL",)))
    assert matches(s, facets(hazards=(SALMONELLA,), origins=()))


def test_product_category_and_origin_filters() -> None:
    s = sub(product_categories=[NUTS], origin_countries=["TR", "US"], include_unclassified=False)
    assert matches(s, facets(products=(NUTS,), origins=("US",)))
    assert not matches(s, facets(products=(NUTS,), origins=("NL",)))
    assert not matches(s, facets(products=(), origins=("US",)))


def test_chinese_subscriptions_only_ever_match_nvwa() -> None:
    # The database enforces sources = ["nvwa"] for zh; the matcher does not rely on it.
    s = sub(locale="zh", sources=[])
    assert matches(s, facets(source="nvwa"))
    assert not matches(s, facets(source="rasff"))
    assert not matches_news(s, facets(source="rasff", notification_type="news"))


def test_rasff_news_ignores_hazard_product_and_country_filters() -> None:
    news = facets(notification_type="news", hazards=(ALLERGENS,), origins=("NL",))
    narrow = sub(
        sources=["rasff"],
        hazard_categories=[SALMONELLA],
        origin_countries=["TR"],
        include_unclassified=False,
    )
    assert matches_news(narrow, news)
    assert not matches_news(sub(sources=["nvwa"]), news)
    assert matches_news(sub(), news)
    # Not News, or out of scope: no.
    assert not matches_news(sub(), facets(notification_type="alert"))
    assert not matches_news(sub(), facets(notification_type="news", product_type="non-food"))


def test_unknown_filter_keys_and_missing_dimensions_mean_no_restriction() -> None:
    s = SubscriptionFilter.from_row(
        {"locale": "nl", "filters": {"sources": ["rasff"]}, "include_unclassified": False}
    )
    assert matches(s, facets(hazards=(), origins=()))
