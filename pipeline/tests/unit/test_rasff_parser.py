"""RASFF detail parser, driven by real detail responses (additionalInformations removed)."""

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from openfoodalerts.parse.model import ParsedMeasure, ParsedNotification
from openfoodalerts.sources.rasff.parser import is_rasff_news, is_substantial, parse_detail

DETAILS = Path(__file__).parents[1] / "fixtures" / "rasff" / "details"


def detail(notif_id: int) -> dict[str, Any]:
    body: dict[str, Any] = json.loads((DETAILS / f"{notif_id}.json").read_text(encoding="utf-8"))
    return body


def test_core_fields_come_from_the_official_detail() -> None:
    n = parse_detail(detail(881995))
    assert n.source_key == "2026.9489"
    assert n.source_ref == "881995"
    assert n.source_url == "https://webgate.ec.europa.eu/rasff-window/screen/notification/881995"
    assert n.title.startswith("High levels of glycidol and 3-monochloro-1,2-propanediol")
    assert n.notification_type == "information notification for attention"
    assert n.risk_official == "potentially serious"
    assert n.status_official == "ec_validated"
    assert n.product_type == "food"
    assert n.product_type_provenance == "official"
    assert n.product_text == "krupuk (prawn crackers)"
    # 23-10-2026 16:50:28 in Brussels (CEST, UTC+2)
    assert n.published_at == datetime(2026, 10, 23, 14, 50, 28, tzinfo=UTC)


@pytest.mark.parametrize(
    ("notif_id", "product_type"),
    [
        (881936, "feed"),
        (881011, "food contact material"),
        (852666, "non-food"),  # RASFF "animals"
        (819084, "non-food"),  # RASFF "other"
    ],
)
def test_product_type_follows_the_official_rasff_product_type(
    notif_id: int, product_type: str
) -> None:
    n = parse_detail(detail(notif_id))
    assert n.product_type == product_type
    assert n.product_type_provenance == "official"


def test_winter_timestamps_are_brussels_standard_time() -> None:
    n = parse_detail(detail(9670))
    # 24-01-2012 12:18:12 CET (UTC+1); lastUpdate 03-03-2020 15:48:25 CET
    assert n.published_at == datetime(2012, 1, 24, 11, 18, 12, tzinfo=UTC)
    assert n.source_updated_at == datetime(2020, 3, 3, 14, 48, 25, tzinfo=UTC)
    assert n.status_official == "ec_withdrawn"


def test_rasff_news_is_recognizable() -> None:
    news_body = json.loads(
        (DETAILS.parent / "derived" / "news_from_881931.json").read_text(encoding="utf-8")
    )
    news = parse_detail(news_body)
    assert news.notification_type == "news"
    assert is_rasff_news(news)
    assert not is_rasff_news(parse_detail(detail(881931)))


def test_hazards_take_the_name_before_the_last_dash_and_the_official_category() -> None:
    hazards = parse_detail(detail(881995)).hazards
    assert [(h.name, h.category_rasff_id) for h in hazards] == [
        ("glycidyl esters", 21790),
        ("3-monochlor-1,2-propanediol (3-MCPD)", 21790),
    ]
    first = hazards[0]
    assert (first.analytical_result, first.unit, first.max_permitted_level) == (
        "3303",
        "µg/kg - ppb",
        "1000 µg/kg - ppb",
    )
    assert first.sampling_date == date(2026, 8, 31)
    assert first.provenance == "official"
    # spec §16: which of several hazards is primary is not inferred
    assert all(h.is_primary is None for h in hazards)


def test_hazard_names_keep_inner_dashes() -> None:
    names = [h.name for h in parse_detail(detail(852666)).hazards]
    assert "chlorpyrifos - unauthorised substance" in names
    assert "Imidaclopride" in names
    assert len(names) == 7
    feed = parse_detail(detail(881936)).hazards[0]
    assert feed.name == "ragweed (Ambrosia spp.) seeds - too high content of"


def roles(n: ParsedNotification) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for c in n.countries:
        assert c.provenance == "official"
        out.setdefault(c.role, []).append(c.iso2)
    return out


def test_country_roles_come_from_the_organization_flags() -> None:
    n = parse_detail(detail(879728))  # two countries of origin
    assert roles(n) == {
        "distribution": ["BE", "FR"],
        "notifying": ["BE"],
        "operator": ["BE", "FR", "NL"],
        "origin": ["BE", "NL"],
    }
    assert n.source_fields["for_follow_up"] == ["FR", "NL"]


def test_organisations_that_are_not_countries_get_no_role() -> None:
    n = parse_detail(detail(881566))  # INFOSAN ("INFO") is flagged for attention
    assert "INFO" not in {c.iso2 for c in n.countries}
    assert roles(n)["origin"] == ["PH"]
    assert n.source_fields["for_attention"] == ["INFO"]


def test_known_non_country_organisations_are_not_reported_as_unmapped() -> None:
    d = detail(881566)
    d["organizationFlags"] += [
        {
            "organization": {"code": "UO", "description": "unknown origin"},
            "notificationFlags": [{"flagType": "ORIGIN"}],
        },
        {
            "organization": {"code": "EU", "description": "European Commission"},
            "notificationFlags": [{"flagType": "NOTIFYING"}],
        },
    ]
    n = parse_detail(d)
    assert not {"UO", "EU"} & {c.iso2 for c in n.countries}
    assert "unmapped_countries" not in n.source_fields


def test_a_measure_by_a_non_country_organisation_has_no_country() -> None:
    d = detail(881566)
    d["product"]["measures"] = [
        {
            "takenBy": {"id": 5248, "isoCode": "UO", "organizationName": "unknown origin"},
            "actionTaken": {"id": 1, "description": "recall from consumers"},
        }
    ]
    n = parse_detail(d)
    assert [m.country_iso2 for m in n.measures] == [None]
    assert "unmapped_countries" not in n.source_fields


def test_product_categories_include_related_products_once() -> None:
    various = parse_detail(detail(881566))
    assert [c.rasff_id for c in various.product_categories] == [
        18453,  # main product: meat and meat products (other than poultry)
        18445,
        18454,
        18437,
        18435,
        18439,
    ]
    assert all(c.provenance == "official" for c in various.product_categories)
    kelp = parse_detail(detail(879145))  # main and both related products share one category
    assert [c.rasff_id for c in kelp.product_categories] == [18439]


def test_measures_from_main_and_related_products() -> None:
    kelp = parse_detail(detail(879145))
    assert [(m.country_iso2, m.action_rasff_id, m.action_text) for m in kelp.measures] == [
        ("FI", 18827, "no action taken"),
        ("BG", 18383, "informing recipient(s)"),
    ]
    old = parse_detail(detail(9670))
    assert len(old.measures) == 6
    assert old.measures[-1] == ParsedMeasure(country_iso2="HU")  # no action recorded


def test_other_official_fields_are_kept_in_source_fields() -> None:
    f = parse_detail(detail(852666)).source_fields
    assert f["notification_basis"] == "border control - consignment detained"
    assert f["distribution_status"] == "product not (yet) placed on the market"
    assert f["hazard_observed"].startswith("Presencia de residuos de plaguicidas")
    assert f["followups"] == [
        {"number": 1, "date": "26-06-2026 15:25:36", "type": "corrigendum", "by": "EU"}
    ]
    assert "additionalInformations" not in json.dumps(f)


@pytest.mark.parametrize("path", sorted(DETAILS.glob("*.json")), ids=lambda p: p.stem)
def test_every_fixture_parses_with_official_dictionary_values(path: Path) -> None:
    n = parse_detail(json.loads(path.read_text(encoding="utf-8")))
    assert n.published_at is not None
    assert n.product_type is not None
    assert n.product_categories
    assert not {"unmapped_hazard_categories", "unmapped_product_categories"} & set(n.source_fields)
    assert all(h.category_rasff_id is not None for h in n.hazards)


def test_missing_optional_fields_are_left_empty() -> None:
    n = parse_detail(detail(881566))  # no distribution status, no measures, no hazards
    assert n.measures == []
    assert "distribution_status" not in n.source_fields
    assert n.risk_official == "potential risk"


def test_a_detail_without_hazards_has_none() -> None:
    n = parse_detail(detail(881845))
    assert n.hazards == []
    assert n.hazard_text is None


def derived(name: str) -> dict[str, Any]:
    body: dict[str, Any] = json.loads(
        (DETAILS.parent / "derived" / f"{name}.json").read_text(encoding="utf-8")
    )
    return body


@pytest.mark.parametrize(
    ("later", "substantial"),
    [("881995_v2_new_distribution", True), ("881995_v2_text_fix", False)],
)
def test_substantial_rule_on_two_versions_of_a_detail(later: str, substantial: bool) -> None:
    """RASFF (spec §10.3): a new distribution country is substantial, a text fix is not."""
    assert is_substantial(parse_detail(detail(881995)), parse_detail(derived(later))) is substantial
