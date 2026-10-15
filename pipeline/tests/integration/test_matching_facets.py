"""Facets the matcher sees: official and AI classifications alike (spec §10.1)."""

from datetime import UTC, datetime

from openfoodalerts.db.connection import Connection
from openfoodalerts.mail.matching import load_facets
from tests.mail_data import add_country, add_hazard, add_notification, add_product_category

T = datetime(2026, 10, 24, 8, 0, tzinfo=UTC)


def test_facets_include_official_and_ai_values(db: Connection) -> None:
    rasff = add_notification(db, "rasff", "2026.0001", first_seen_at=T)
    add_hazard(db, rasff, 21798)
    add_hazard(db, rasff, 21798)  # two Hazards of one category count once
    add_hazard(db, rasff, None)  # a Hazard without a category adds nothing
    add_product_category(db, rasff, 18451)
    add_country(db, rasff, "TR")
    add_country(db, rasff, "NL", role="distribution")
    nvwa = add_notification(db, "nvwa", "/a/b", first_seen_at=T)
    add_hazard(db, nvwa, 21802, provenance="ai")
    add_product_category(db, nvwa, 18451, provenance="ai")
    add_country(db, nvwa, "BE", provenance="ai")
    bare = add_notification(db, "openfda", "H-1", first_seen_at=T, product_type=None)

    facets = load_facets(db, [rasff, nvwa, bare, rasff])

    assert facets[rasff].source == "rasff"
    assert facets[rasff].hazard_categories == {21798}
    assert facets[rasff].product_categories == {18451}
    assert facets[rasff].origin_countries == {"TR"}
    assert facets[nvwa].hazard_categories == {21802}
    assert facets[nvwa].product_categories == {18451}
    assert facets[nvwa].origin_countries == {"BE"}
    assert facets[bare].product_type is None
    assert facets[bare].hazard_categories == frozenset()
    assert load_facets(db, []) == {}
