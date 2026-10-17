"""Instant email trigger rules (spec §10.4), on top of the shared filter matching."""

from typing import Any

import pytest

from openfoodalerts.mail.matching import (
    NotificationFacets,
    SubscriptionFilter,
    instant_trigger,
    matches_instant,
)

SALMONELLA = 21801
ALLERGENS = 21798


def sub(
    *,
    instant: list[str],
    locale: str = "en",
    include_unclassified: bool = True,
    **filters: list[Any],
) -> SubscriptionFilter:
    return SubscriptionFilter.from_row(
        {
            "locale": locale,
            "filters": {"sources": [], **filters},
            "include_unclassified": include_unclassified,
            "instant_sources": instant,
        }
    )


def facets(
    *,
    source: str,
    notification_type: str,
    product_type: str | None = "food",
    risk_official: str | None = None,
    hazards: tuple[int, ...] = (),
) -> NotificationFacets:
    return NotificationFacets(
        id=1,
        source=source,
        product_type=product_type,
        notification_type=notification_type,
        hazard_categories=frozenset(hazards),
        product_categories=frozenset(),
        origin_countries=frozenset(),
        risk_official=risk_official,
    )


def rasff(notification_type: str, **kw: Any) -> NotificationFacets:
    return facets(source="rasff", notification_type=notification_type, **kw)


def fda(risk_official: str | None, **kw: Any) -> NotificationFacets:
    return facets(
        source="openfda", notification_type="enforcement report", risk_official=risk_official, **kw
    )


def nvwa(product_type: str | None, **kw: Any) -> NotificationFacets:
    return facets(
        source="nvwa", notification_type="safety warning", product_type=product_type, **kw
    )


@pytest.mark.parametrize(
    ("notification_type", "expected"),
    [
        ("alert notification", True),
        ("Alert notification", True),
        ("information notification for attention", False),
        ("information notification for follow-up", False),
        ("border rejection notification", False),
        ("non-member country notification", False),
        ("news", False),
    ],
)
def test_rasff_triggers_on_alert_notifications_only(notification_type: str, expected: bool) -> None:
    assert instant_trigger(rasff(notification_type)) is expected


def test_rasff_alerts_on_feed_and_food_contact_material_trigger_too() -> None:
    assert instant_trigger(rasff("alert notification", product_type="feed"))
    assert instant_trigger(rasff("alert notification", product_type="food contact material"))


@pytest.mark.parametrize(
    ("classification", "expected"),
    [("Class I", True), ("Class II", False), ("Class III", False), ("Not Yet Classified", False)],
)
def test_fda_triggers_on_class_i_only(classification: str, expected: bool) -> None:
    assert instant_trigger(fda(classification)) is expected


def test_fda_without_a_classification_does_not_trigger() -> None:
    assert not instant_trigger(fda(None))


@pytest.mark.parametrize(
    ("product_type", "expected"),
    [
        ("food", True),
        ("feed", False),
        ("food contact material", False),
        ("non-food", False),
        # Waiting for T5 (product_type NULL, provenance 'pending') is not "T5 abstained".
        (None, False),
    ],
)
def test_nvwa_triggers_on_food_warnings(product_type: str | None, expected: bool) -> None:
    assert instant_trigger(nvwa(product_type)) is expected


def test_only_sources_chosen_for_instant_email() -> None:
    alert = rasff("alert notification")
    assert matches_instant(sub(instant=["rasff"]), alert)
    assert not matches_instant(sub(instant=["nvwa"]), alert)
    assert not matches_instant(sub(instant=[]), alert)


def test_the_other_filters_apply() -> None:
    alert = rasff("alert notification", hazards=(SALMONELLA,))
    assert matches_instant(sub(instant=["rasff"], hazard_categories=[SALMONELLA]), alert)
    assert not matches_instant(sub(instant=["rasff"], hazard_categories=[ALLERGENS]), alert)
    # instant_sources ⊆ sources (spec §10.1): a source filtered out gets nothing.
    assert not matches_instant(sub(instant=["rasff"], sources=["nvwa"]), alert)


def test_out_of_scope_never_triggers() -> None:
    assert not matches_instant(
        sub(instant=["rasff"]), rasff("alert notification", product_type="non-food")
    )
    assert not matches_instant(sub(instant=["openfda"]), fda("Class I", product_type="non-food"))


def test_rasff_news_never_triggers() -> None:
    assert not matches_instant(sub(instant=["rasff"]), rasff("news"))


def test_chinese_subscriptions_get_nvwa_only() -> None:
    zh = sub(instant=["nvwa", "rasff"], locale="zh", sources=["nvwa"])
    assert matches_instant(zh, nvwa("food"))
    assert not matches_instant(zh, rasff("alert notification"))
