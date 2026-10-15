"""The keyword heuristic guesses a RASFF Hazard category from source text (EN and NL).

Examples are real FDA recall reasons and NVWA summary sentences (2023-2026).
"""

import pytest

from openfoodalerts.eval.keywords import RULES, guess_from_snapshot, guess_hazard_category
from openfoodalerts.sources.rasff.lookups import Dictionary, read_seed


@pytest.mark.parametrize(
    ("text", "category"),
    [
        # openFDA reason_for_recall
        ("Potential Listeria Monocytogenes", "pathogenic micro-organisms"),
        ("Products may contain Salmonella", "pathogenic micro-organisms"),
        (
            "May be under-processed resulting in growth of Clostridium botulinum",
            "pathogenic micro-organisms",
        ),
        ("Product may contain undeclared peanut, soy, and wheat.", "allergens"),
        ("Contains statement does not declare Anchovy", "allergens"),
        (
            "Undeclared allergens: Milk, Peanuts, Soy, and Wheat. Undeclared color additives: "
            "FD&C red #40, red #6.",
            "allergens",
        ),
        ("Undeclared colors FD&C Yellow #6, and FD&C Red 40", "food additives and flavourings"),
        ("Foreign object: metal fragments", "foreign bodies"),
        ("Foreign Material (plastic).", "foreign bodies"),
        ("Elevated levels of Lead, cadmium and arsenic", "heavy metals"),
        (
            "The products contain DMHA and/or hordenine which FDA has determined are not "
            "acceptable dietary ingredients.",
            "composition",
        ),
        ("May be contaminated with fluid from a reach truck", "chemical contamination (other)"),
        ("Incomplete pasteurization", "poor or insufficient controls"),
        (
            "Product mislabeled.  The back label states Organic Cashews.",
            "labelling absent/incomplete/incorrect",
        ),
        ("Products may contain aflatoxin above the action level", "mycotoxins"),
        # NVWA summary sentences
        ("Het product bevat sulfiet. Dit staat niet op het etiket.", "allergens"),
        ("Veiligheidswaarschuwing Gazpacho van Marqt (melkallergie)", "allergens"),
        (
            "In het product is de bacterie Listeria monocytogenes aanwezig.",
            "pathogenic micro-organisms",
        ),
        (
            "De shigatoxine-producerende E. coli-bacterie (STEC) kan aanwezig zijn",
            "pathogenic micro-organisms",
        ),
        ("In de dumplings kunnen stukjes glas zitten.", "foreign bodies"),
        ("De worst kan metaaldeeltjes bevatten.", "foreign bodies"),
        ("In de kroketten kunnen stukjes bot zitten.", "foreign bodies"),
        (
            "Er staat een verkeerde houdbaarheidsdatum op de verpakking",
            "labelling absent/incomplete/incorrect",
        ),
        ("In het product is ethyleenoxide aangetroffen.", "pesticide residues"),
        ("Het product is mogelijk besmet met hepatitis A", "pathogenic micro-organisms"),
        ("Het product bevat mogelijk schimmel.", "non-pathogenic micro-organisms"),
        ("In de bloem zitten mogelijk insecten.", "parasitic infestation"),
        # second round, from unmatched real texts
        ("Potential Cyclospora contamination.", "pathogenic micro-organisms"),
        ("Undeclared Yellow 5 & 6, Red 3, and Blue 1", "food additives and flavourings"),
        ("In de worst kunnen vreemde voorwerpen aanwezig zijn.", "foreign bodies"),
        ("Er bestaat een kans dat dit product glas bevat.", "foreign bodies"),
        ("Het product is onvoldoende gesteriliseerd.", "poor or insufficient controls"),
        (
            "Inaccurately declared nutrients including Potassium (overstated)",
            "labelling absent/incomplete/incorrect",
        ),
        ("Potential to contain glass", "foreign bodies"),
        ("Product was not stored under refrigeration", "poor or insufficient controls"),
        ("discovered swollen and leaking cans", "packaging defective / incorrect"),
        (
            "potential presence of a very thin metal strand embedded in the gummies",
            "foreign bodies",
        ),
    ],
)
def test_guesses_the_category(text: str, category: str) -> None:
    assert guess_hazard_category(text) == category


@pytest.mark.parametrize(
    "text",
    [
        "The firm was notified by its supplier; this could lead to a recall.",
        "Japan Harvest rice crackers in a glass jar",
        "Potential microbial contamination",
        "Dirk waarschuwt voor Wahid Knakworst kip pak 4 stuks.",  # pak = pack, not PAK
        "Non-GMO rBGH-Free Whey Protein Concentrate",
        "",
    ],
)
def test_no_guess_without_a_clear_signal(text: str) -> None:
    """'lead' as a verb, 'glass jar' (packaging), vague wording: no category."""
    assert guess_hazard_category(text) is None


def test_the_recall_reason_wins_over_the_product_description() -> None:
    snapshot = {
        "product_description": "Dole Diced Southern Slaw, Preservative Free",
        "reason_for_recall": "Potential to contain glass",
    }
    assert guess_from_snapshot(snapshot) == "foreign bodies"


def test_the_whole_text_is_the_fallback() -> None:
    snapshot = {"product_description": "Peanut butter with Salmonella", "reason_for_recall": "?"}
    assert guess_from_snapshot(snapshot) == "pathogenic micro-organisms"


def test_nvwa_product_lines_count_only_as_fallback() -> None:
    snapshot = {
        "title": "Veiligheidswaarschuwing Jumbo pindakaas",
        "summary": "Er kan glas in zitten.",
        "products": "Pindakaas met sulfiet",
    }
    assert guess_from_snapshot(snapshot) == "foreign bodies"


def test_every_rule_names_a_seeded_rasff_category() -> None:
    names = {e.name for e in read_seed(Dictionary.HAZARD_CATEGORY)}
    assert {category for category, _ in RULES} <= names
