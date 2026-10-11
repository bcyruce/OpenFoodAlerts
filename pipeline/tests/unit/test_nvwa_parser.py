"""NVWA detail page parser on real snapshots (2026-10-25) of www.nvwa.nl."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from openfoodalerts.parse.model import ParsedNotification
from openfoodalerts.sources.nvwa.parser import match_label, parse_detail

NEWS = "/actueel/nieuws/2026/10"
POKEBOWL = f"{NEWS}/24/veiligheidswaarschuwing-ah-pokebowl-sticky-tempeh-allergenen"


def page(
    fixtures_dir: Path, name: str, path: str = "/x", item: dict[str, Any] | None = None
) -> ParsedNotification:
    html = (fixtures_dir / "nvwa" / "detail" / f"{name}.html").read_bytes()
    return parse_detail(html, path, item)


def fields(parsed: ParsedNotification, group: int) -> dict[str, str]:
    return {f["key"]: f["value"] for f in parsed.source_fields["products"][group]["fields"]}


def test_new_list_page(fixtures_dir: Path) -> None:
    item = {"id": {"raw": "doc-6adcc4b711495c1361ca4af2"}, "url": {"raw": POKEBOWL}}
    n = page(fixtures_dir, "ah-pokebowl-allergenen", POKEBOWL, item)
    assert n.source_key == POKEBOWL
    assert n.source_url == f"https://www.nvwa.nl{POKEBOWL}"
    assert n.source_ref == "doc-6adcc4b711495c1361ca4af2"
    assert n.title == "Veiligheidswaarschuwing AH Pokebowl sticky tempeh (allergenen)"
    assert n.published_at == datetime(2026, 10, 24, 14, 35, tzinfo=UTC)
    assert n.source_updated_at == datetime(2026, 10, 24, 14, 46, 9, 586000, tzinfo=UTC)
    assert n.notification_type == "safety warning"
    assert n.risk_official is None
    assert n.summary_source == (
        "Albert Heijn waarschuwt voor AH Pokebowl sticky tempeh. Op de verpakking staat een"
        " vegan-logo, terwijl het product ei bevat. Eet het product niet als u allergisch bent"
        " voor ei of een veganistisch dieet volgt."
    )
    # No labelled list: the sentence is kept as it is.
    assert n.product_text == "Het gaat om de AH Pokebowl sticky tempeh met alle houdbaarheidsdata."
    sf = n.source_fields
    assert sf["recall_links"] == ["https://www.ah.nl/mededeling"]
    assert sf["update_notes"] == []
    assert sf["content_type"] == "pro:newsDocument"
    assert sf["information_type"] == "Nieuwsbericht"


def test_update_note_is_split_from_the_summary(fixtures_dir: Path) -> None:
    n = page(fixtures_dir, "cook-korianderzaad-update")
    assert n.source_fields["update_notes"] == [
        "Update 13 oktober 2026: Ook Odin Groothandel waarschuwt voor dit product. Bij Odin is"
        " het product bekend onder artikelnummer 10749."
    ]
    assert n.summary_source == (
        "Udea en Odin Groothandel waarschuwen voor Cook korianderzaad gemalen. Het product"
        " bevat mogelijk salmonella. Gebruik het korianderzaad niet."
    )
    assert fields(n, 0) == {
        "name": "Cook korianderzaad Gemalen",
        "ean": "3417960022619",
        "article_number": "10749",
        "best_before": "08-2028",
        "sold_at": "Ekoplaza en andere bio-winkels.",
    }
    labels = [f["label"] for f in n.source_fields["products"][0]["fields"]]
    assert "Artikelnummer Odin" in labels
    assert n.source_fields["recall_links"] == [
        "https://www.udea.nl/nieuws/detail/belangrijke-veiligheidswaarschuwing-cook-korianderzaad-gemalen-30-g",
        "https://www.odin.nl/actueel/veiligheidswaarschuwingen/-191625-recall-korianderzaad-gemalen-kerrie-mild-van-cook/",
        "https://www.ekoplaza.nl/nl/actueel/artikel/veiligheidswaarschuwing-voor-cook-gemalen-korianderzaad",
    ]


def test_several_retailers_and_products(fixtures_dir: Path) -> None:
    n = page(fixtures_dir, "kipdijspiesjes-multi")
    products = n.source_fields["products"]
    assert [p.get("heading") for p in products] == [
        "Boni",
        "DekaMarkt",
        "Dirk",
        "Nettorama",
        "Plus",
        "Plus",
        "Poiesz",
        "Spar",
    ]
    assert fields(n, 4) == {
        "name": "Plus kipdijspies BLK 100g",
        "ean": "8718989697518",
        "use_by": "23-08-2026, 29-08-2026, 30-08-2026 en 01-09-2026",
    }
    assert fields(n, 5)["name"] == "Plus kipdijspies BLK 145g"
    # A product line without a label stays verbatim in product_text.
    assert "Spar kipdijspies BLK 100g" in (n.product_text or "").splitlines()
    assert "Boon kipdijspies BLK 100g" in (n.product_text or "").splitlines()
    assert len(n.source_fields["recall_links"]) == 7
    assert n.summary_source == (
        "Diverse supermarkten waarschuwen voor kipdijspiesjes. In de verpakking zitten mogelijk"
        " onvoldoende gegaarde kipdijspiesjes. Eet het product niet."
    )


def test_archive_page_with_products_inside_the_intro(fixtures_dir: Path) -> None:
    n = page(fixtures_dir, "archive-jumbo-pennywafels-2023")
    assert n.title == "Veiligheidswaarschuwing Jumbo Pennywafels"
    assert n.published_at == datetime(2023, 10, 4, 10, 34, tzinfo=UTC)
    assert n.summary_source is not None
    assert n.summary_source.endswith("Eet het product niet.")
    assert "Om welk product" not in n.summary_source
    assert "Streepjescode" not in n.summary_source
    assert n.product_text == "Jumbo Pennywafels"
    assert fields(n, 0) == {"ean": "8718452584406", "best_before": "01-06-2024"}
    assert n.source_fields["content_type"] == "pro:downloadDocument"
    assert n.source_fields["information_type"] == "Waarschuwing"


def test_labels_without_colon(fixtures_dir: Path) -> None:
    n = page(fixtures_dir, "archive-rammelaar-2023")
    assert n.product_text == "PRE Rammelaar Pure White"
    assert fields(n, 0) == {
        "article_number": "5333636 (zie care label)",
        "batch": "072021 (zie care label)",
        "sold_period": "Verkocht vanaf januari 2022 t/m augustus 2023",
    }


def test_nested_headings_and_sales_sentences(fixtures_dir: Path) -> None:
    n = page(fixtures_dir, "archive-powerbanks-tkmaxx-update")
    assert n.source_fields["update_notes"] == [
        "Update 1 juni 2026: de Power Evo Wireless Charging Power Bank Volt 5 is toegevoegd"
        " aan dit overzicht."
    ]
    lines = (n.product_text or "").splitlines()
    assert lines[:2] == ["Verschillende powerbanks van POM", "TITAN CHARGE"]
    titan = n.source_fields["products"][1]
    assert titan["heading"] == "TITAN CHARGE"
    assert {f["key"]: f["value"] for f in titan["fields"]} == {
        "model": "P2G5080, P2G5080B, P2G5080W, P2G5080BK, P2G5080WT"
    }
    periods = [
        f["value"]
        for p in n.source_fields["products"]
        for f in p["fields"]
        if f["key"] == "sold_period"
    ]
    assert periods[0] == "Verkocht in de winkels van TK Maxx van augustus 2024 tot en met mei 2026."
    assert len(periods) == 3


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (
            "dental-floss-picks",
            {
                "name": "Sippin Pretty Hot Cocoa & Cream Dental Floss Picks",
                "brand": "Yes Studio",
                "ean": "5016610011485",
                "article_number": "YS10HCFPN",
                "batch": "455/05/26",
                "sold_period": "tot en met 25 september 2026",
                "sold_at": "Normal-winkels",
            },
        ),
        (
            "imoshion-powerbank",
            {
                "name": "imoshion MagSafe Powerbank 10.000 mAh, draadloze powerbank",
                "article_number": "IM-PB-0007",
                "batch": "2024-06-0004 en 2024-09-0007",
                "ean": "8720922101068, 8720922101075, 8720922183033, 8720922183064, 8720922183071,"
                " 8721064033798, 8721064033804, 8721064033811 en 8721064033828",
                "sold_at": "smartphonehoesjes.nl, handyhuelle.de, ploonk.fr, coquedetelephone.fr,"
                " bol.com, MediaMarkt, ANWB, Kruidvat, Kaufland, Cdiscount, Fnac, Boulanger, eBay,"
                " Octopia en TikTok",
                "sold_period": "juli 2024 t/m juni 2026",
            },
        ),
        (
            "amogusti-olijven-update",
            {
                "name": "Amogusti olijven gevuld met citroen 200 gram",
                "ean": "8718247443611",
                "best_before": "18-06-2028",
                "batch": "N3A6169",
            },
        ),
        (
            "kinderzitje-hamax-buddy",
            {
                "name": "Baby seat HAMAX Buddy",
                "article_number": "4091054",
                "model": "8591602",
                "ean": "70297755203498",
                "sold_period": "van 01-01-2022 tot 06-08-2026",
            },
        ),
    ],
)
def test_product_labels(fixtures_dir: Path, name: str, expected: dict[str, str]) -> None:
    assert fields(page(fixtures_dir, name), 0) == expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Geproduceerd tussen tijdstip 16:00 en 18:00", None),  # a time, not a label
        ("Productcode: B20", ("article_number", "Productcode", "B20")),
        ("Batchnummer(s) / THT: L123", ("batch", "Batchnummer(s) / THT", "L123")),
        ("Let op: alleen deze partij", None),
    ],
)
def test_label_matching(line: str, expected: tuple[str, str, str] | None) -> None:
    assert match_label(line) == expected


def test_link_lists_in_the_intro_are_links_not_summary() -> None:
    html = (
        b"<main><div class='intro'><div class='rich-text'>"
        b"<p>Meerdere supermarkten waarschuwen voor wijn. Consumeer dit product niet.</p>"
        b"<p>Zie de website van:</p><ul>"
        b"<li><a rel='external' href='https://a.example/recall'>A</a></li>"
        b"<li><a rel='external' href='https://b.example/recall'>B</a></li></ul>"
        b"</div></div></main>"
    )
    n = parse_detail(html, "/x")
    assert (
        n.summary_source
        == "Meerdere supermarkten waarschuwen voor wijn. Consumeer dit product niet."
    )
    assert n.source_fields["recall_links"] == [
        "https://a.example/recall",
        "https://b.example/recall",
    ]


def test_a_withdrawn_warning_says_so_in_its_status() -> None:
    html = (
        b'<script id="elastic-content" type="application/json">{"pageTitle":'
        b'"Veiligheidswaarschuwing ingetrokken - Salami van Picnic en ALDI"}</script>'
        b"<main><div class='intro'><div class='rich-text'><p>De waarschuwing is ingetrokken.</p>"
        b"</div></div></main>"
    )
    assert parse_detail(html, "/x").status_official == "withdrawn"
    assert parse_detail(html.replace(b"ingetrokken -", b""), "/x").status_official is None


def test_product_names_go_to_product_text(fixtures_dir: Path) -> None:
    n = page(fixtures_dir, "archive-oesters-update")
    assert n.product_text == "Bevroren Oesters 226G van Surasang"
    assert fields(n, 0)["sold_period"] == "12-04-2026 tot en met 10-06-2026"


def test_tracking_parameters_are_dropped_from_recall_links(fixtures_dir: Path) -> None:
    n = page(fixtures_dir, "amogusti-olijven-update")
    assert n.source_fields["recall_links"][-1] == (
        "https://www.dekamarkt.nl/meer/belangrijke-veiligheidswaarschuwing-33"
    )


def test_images_are_never_copied(fixtures_dir: Path) -> None:
    for name in ("ah-pokebowl-allergenen", "kipdijspiesjes-multi", "archive-oesters-update"):
        dumped = json.dumps(page(fixtures_dir, name).model_dump(mode="json"))
        assert "/site/binaries/" not in dumped
        assert ".jpg" not in dumped
