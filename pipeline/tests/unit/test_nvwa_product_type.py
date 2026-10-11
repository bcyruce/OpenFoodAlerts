"""Rule part of T5 for NVWA (spec §4.2): clear cases only, the rest waits for the LLM."""

from pathlib import Path

import pytest

from openfoodalerts.normalize.product_type import nvwa_product_type
from openfoodalerts.sources.nvwa.parser import parse_detail


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("kinderzitje-hamax-buddy", "non-food"),
        ("imoshion-powerbank", "non-food"),
        ("archive-powerbanks-tkmaxx-update", "non-food"),
        ("archive-rammelaar-2023", "non-food"),
        ("dental-floss-picks", "non-food"),  # "Hot Cocoa & Cream" is a flavour, not food
        ("peper-zoutmolens-primark", None),  # food contact material: for T5
        ("ah-pokebowl-allergenen", "food"),
        ("cook-korianderzaad-update", "food"),
        ("kipdijspiesjes-multi", "food"),
        ("archive-jumbo-pennywafels-2023", "food"),
        ("archive-aldi-salade-2025", "food"),
        ("archive-oesters-update", "food"),
        ("amogusti-olijven-update", "food"),
    ],
)
def test_real_warnings(fixtures_dir: Path, fixture: str, expected: str | None) -> None:
    html = (fixtures_dir / "nvwa" / "detail" / f"{fixture}.html").read_bytes()
    parsed = parse_detail(html, "/x")
    assert parsed.product_type == expected
    assert parsed.product_type_provenance == ("rule" if expected else "pending")


@pytest.mark.parametrize(
    ("title", "summary", "expected"),
    [
        # Pet food is feed, not food: conflicting signals go to T5.
        (
            "Veiligheidswaarschuwing hondensnacks",
            "Mogelijk salmonella. Geef het niet aan uw hond.",
            None,
        ),
        # Nothing recognisable.
        ("Veiligheidswaarschuwing Kartonnen doos", "Gebruik het product niet.", None),
        # A nickel allergy is not a food allergen.
        (
            "Veiligheidswaarschuwing oorbellen",
            "Niet dragen als u allergisch bent voor nikkel.",
            "non-food",
        ),
        ("Veiligheidswaarschuwing gummies", "Eet het snoep niet.", "food"),
        # Seen in the real backfill (2026-10-25):
        (
            "Veiligheidswaarschuwing biologische chiazaad 275 gram van Bio+",
            "In het product is een hoeveelheid pesticiden gevonden die hoger is dan wettelijk is"
            " toegestaan. Consumeer dit product niet.",
            "food",
        ),
        (
            "Veiligheidswaarschuwing Les Perles Du Homard bier van brouwerij De Kromme Haring",
            "Flessen kunnen bij hoge temperatuur en/of temperatuurschommelingen een hoge druk"
            " opbouwen.",
            None,
        ),
        ("Veiligheidswaarschuwing gelegenheidsjurken American Princess", "", "non-food"),
        ("Veiligheidswaarschuwing diverse reddingsvesten van Helly Hansen", "", "non-food"),
        ("Veiligheidswaarschuwing speel- en knutselzand van HEMA", "", "non-food"),
        ("Veiligheidswaarschuwing VistaSonic haardroger", "", "non-food"),
        ("Veiligheidswaarschuwing SMÖJTRÄD geurloze kroonkaars van IKEA", "", "non-food"),
        ("Veiligheidswaarschuwing Harvest granola", "Eet het product niet.", "food"),
        (
            "Veiligheidswaarschuwing Moutextract poeder Amber 18 EBC van Brewferm",
            "Gebruik het poeder niet als u een glutenintolerantie heeft.",
            "food",
        ),
        ("Veiligheidswaarschuwing badspeelgoed 'My First Bath Animals'", "", "non-food"),
        ("Veiligheidswaarschuwing Dunlop Fietshelmen", "", "non-food"),
        ("Veiligheidswaarschuwing Babboe bakfietsen", "", "non-food"),
        ("Veiligheidswaarschuwing Kinderjassen van Zeeman", "", "non-food"),
        ("Veiligheidswaarschuwing Wenger universele reisadapter", "", "non-food"),
        # Look like food, are not: left to T5 rather than guessed.
        (
            "Veiligheidswaarschuwing Ice Cube Fruits 12 stuks van Schou Company",
            "Kinderen kunnen het product verwarren met voedsel. Gebruik het product niet.",
            None,
        ),
        (
            "Veiligheidswaarschuwing LESLI kleurige sterretjes 5 stuks van Dirk",
            "Bij het aansteken van de sterretjes kan een steekvlam ontstaan.",
            None,
        ),
        # Lamprey and spelt must not trigger "lamp" or a toy rule.
        ("Veiligheidswaarschuwing gerookte lamprei", "Bevat listeria.", "food"),
        (
            "Veiligheidswaarschuwing speltkoekjes",
            "Eet de koekjes niet als u allergisch bent voor melk.",
            "food",
        ),
    ],
)
def test_rules(title: str, summary: str, expected: str | None) -> None:
    assert nvwa_product_type(title, summary, None) == expected
