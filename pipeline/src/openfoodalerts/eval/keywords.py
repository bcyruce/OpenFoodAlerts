"""Keyword rules that guess a RASFF Hazard category from source text (English and Dutch).

Two uses:

- ticket 12: a transparent pre-label ("hazard group") for NVWA and openFDA Notifications,
  which have no official Hazard category, so the eval sample can be stratified by
  Source x hazard group. The guess is never a Label; the domain expert labels every item.
- ticket 15: the "keyword rules" baseline (spec §7.2). Map the category to a T1 label with
  `Taxonomy.label_for_name`; no match means abstain.

Rules are tried in priority order and the first match wins, so a text naming both an
undeclared allergen and an undeclared colour counts as allergens (the usual recall
reason). The rules return RASFF category names, not T1 labels, so they survive changes of
the label set: the taxonomy CSV maps names to labels ("poor or insufficient controls" ->
"other" in the v1 draft).

Patterns avoid bare ambiguous words: "lead" only with "levels of" / "elevated", "glass" /
"plastic" only next to "pieces", "fragments" or a Dutch "zit/bevat" construction (not
"glass jar"), "adulterated" never (FDA uses it as a legal term for every recall).
"""

import re
from collections.abc import Mapping

_RULES_SOURCE: list[tuple[str, list[str]]] = [
    (
        "pathogenic micro-organisms",
        [
            r"\blisteria",
            r"\bsalmonell",
            r"\bE\.?\s?coli\b",
            r"\bSTEC\b",
            r"shiga",
            r"botulin",
            r"norovirus",
            r"hepatitis",
            r"cronobacter",
            r"campylobacter",
            r"bacillus\s+cereus",
            r"cereulide",
            r"staphylococ",
            r"\bvibrio",
            r"shigella",
            r"yersinia",
            # protozoa: RASFF files Cyclospora / Cryptosporidium with the pathogens
            r"cyclospora",
            r"cryptosporid",
            r"clostridium\s+perfringens",
        ],
    ),
    (
        "allergens",
        [
            r"allerg",
            r"gluten",
            r"\bcross-?contact",
            r"\b(peanut|milk|egg|soy|wheat|sesame|tree\s?nut)\s+(protein|residue)",
            r"\bsulfiet",
            r"\bsulph?ites?\b",
            r"\bsulfites?\b",
            r"\b(undeclared|not\s+declared?|does\s+not\s+declare|not\s+listed|omitted)\W+"
            r"(\w+\W+){0,6}?(milk|eggs?|peanuts?|tree\s?nuts?|nuts?|almonds?|walnuts?|cashews?"
            r"|pecans?|hazelnuts?|pistachios?|macadamia|soy\w*|wheat|fish|anchov\w+|sardines?"
            r"|tuna|salmon|cod|shellfish|crustacean\w*|shrimp|crab|lobster|clams?|mussels?"
            r"|oysters?|sesame|mustard|celery|lupin\w*|coconut)\b",
        ],
    ),
    (
        "foreign bodies",
        [
            r"\bforeign\s+(object|material|matter|bod(y|ies)|particle)",
            r"\b(metal|glass|plastic|wood(en)?|rubber|stone|bone|rock|wire)\s+"
            r"(fragments?|pieces?|particles?|shards?|shavings?|chips?|filaments?|strands?)\b",
            r"\bcontain\w*\s+(pieces\s+of\s+)?(glass|metal|plastic|wood|rubber)\b",
            r"\bpieces?\s+of\s+(\w+\s+)?(metal|glass|plastic|wood|rubber|bone|a\s+pen)\b",
            r"\bcontaminat\w*\s+with\s+(\w+\s+){0,2}(plastic|metal|glass|wood|rubber)\b",
            r"\b(glas|metaal|plastic|kunststof|hout|bot|steen|koper|rubber)"
            r"(deeltjes?|splinters?|scherven|stukjes?|draad|draadjes)\b",
            r"\bstukjes?\s+(\w+\W+){0,3}?(glas|metaal|metaaldraad|plastic|kunststof|hout|bot|koper"
            r"|rubber|steen)\b",
            r"\bharde\s+stukjes\b",
            r"\bvreemde?\s+(voorwerp|delen|deeltjes|materia)",
            r"\b(plastic|glas|metaal)\b\W+(\w+\W+){0,3}?(zitten|zit|bevat|bevatten|aanwezig)\b",
            r"\b(bevat|bevatten|zitten|zit|kan\s+er)\W+(\w+\W+){0,3}?(plastic|glas|metaal)\b",
        ],
    ),
    (
        "mycotoxins",
        [
            r"aflatox",
            r"ochratox",
            r"\bpatulin",
            r"deoxynivalenol",
            r"fumonisin",
            r"zearalenon",
            r"mycotox",
            r"\bcitrinin",
        ],
    ),
    (
        "pesticide residues",
        [
            r"pesticid",
            r"ethylene\s+oxide",
            r"ethyleenoxide",
            r"2-chloroethanol",
            r"chloorethanol",
            r"chlorpyrifos",
            r"bestrijdingsmiddel",
            r"gewasbeschermingsmiddel",
        ],
    ),
    (
        "heavy metals",
        [
            r"\blevels?\s+of\s+lead\b",
            r"\b(elevated|high|excessive|unsafe|increased)\s+lead\b",
            r"\blead\s+(levels?|content|contamination|poisoning)\b",
            r"\b(cadmium|arsenic|mercury|lood|arseen|kwik)\b",
        ],
    ),
    (
        "natural toxins (other)",
        [
            r"ciguat",
            r"tetrodotox",
            r"\btropane",
            r"atropin",
            r"scopolamin",
            r"pyrrolizidin",
            r"\bergot",
            r"moederkoorn",
            r"solanin",
            r"glycoalkaloid",
            r"amygdalin",
            r"cyanide",
            r"blauwzuur",
            r"hydrocyan",
            r"okadai",
            r"saxitox",
            r"domoic",
            r"shellfish\s+poison",
            r"\bamanit",
            r"\bricin",
            r"grayanotox",
        ],
    ),
    (
        "biological contaminants",
        [r"histamin", r"scombro"],
    ),
    (
        "residues of veterinary medicinal products",
        [
            r"chloramphenicol",
            r"nitrofuran",
            r"malachite\s+green",
            r"malachietgroen",
            r"crystal\s+violet",
            r"antibiotic\w*\s+(residue|detected|found)",
            r"residues?\s+of\s+(\w+\s+)?antibiotic",
            r"resten\s+van\s+antibiotica",
            r"veterinary\s+(drug|medicin)",
            r"diergeneesmiddel",
            r"enrofloxacin",
            r"sulfonamide",
            r"tetracyclin",
            r"doxycyclin",
            r"ivermectin",
        ],
    ),
    (
        "composition",
        [
            r"unapproved\s+(new\s+)?(drug|ingredient)",
            r"not\s+(an?\s+)?acceptable\s+dietary\s+ingredient",
            r"sildenafil",
            r"tadalafil",
            r"vardenafil",
            r"sibutramin",
            r"phenolphthalein",
            r"\bDMHA\b",
            r"\bDMAA\b",
            r"hordenine",
            r"kratom",
            r"tianeptin",
            r"phenibut",
            r"yohimbin",
            r"ephedr",
            r"\bsudan\s+(red|[1-4]|i{1,3}v?)\b",
            r"(too\s+high|excessive|excess)\s+(\w+\s+){0,2}vitamin",
            r"niet\s+toegestane?\s+(stof|ingredi)",
            r"\bgeneesmiddel",
        ],
    ),
    (
        "food additives and flavourings",
        [
            r"colou?r\s+additives?",
            r"FD&C",
            r"\b(yellow|red|blue|green)\s*(#|no\.?\s*)\s*\d+",
            r"\b(yellow|blue)\s+\d\b",
            r"\bred\s+(3|40)\b",
            r"glycerol",
            r"titanium\s+dioxide",
            r"tartrazine",
            r"preservative",
            r"conserveermiddel",
            r"kleurstof",
            r"zoetstof",
            r"sweetener",
            r"\bsorbic\b",
            r"benzoic|benzoate",
        ],
    ),
    (
        "migration",
        [r"\bmigrat", r"primary\s+aromatic\s+amines", r"aromatische\s+aminen"],
    ),
    (
        "radiation",
        [r"irradiat", r"bestraald", r"bestraling", r"radioactiv", r"\bca?esium"],
    ),
    (
        "GMO / novel food",
        [
            r"genetically\s+modified",
            r"(?<!non-)(?<!non\s)\bGMO\b",
            r"(?<!geen\s)\bGGO\b",
            r"genetisch\s+gemodificeerd",
            r"novel\s+food",
            r"nieuwe\s+voedingsmiddel",
            r"cannabidiol",
            r"\bCBD\b",
        ],
    ),
    (
        "TSEs",
        [r"\bBSE\b", r"\bTSEs?\b", r"specified\s+risk\s+material"],
    ),
    (
        "environmental pollutants",
        [r"dioxin", r"\bPCBs?\b", r"\bPFAS\b", r"\bPFOS\b", r"perfluor"],
    ),
    (
        "industrial contaminants",
        [
            r"3-?MCPD",
            r"glycidyl",
            r"acrylamid",
            r"\bbenzene\b",
            r"\bbenzeen\b",
            r"mineral\s+oil",
            r"minerale\s+olie",
            r"\bMOAH\b",
            r"\bMOSH\b",
            r"benzo\W?\(?a\)?\W?pyre",
            r"\bPAHs?\b",
            # not "PAK": Dutch "pak" is a pack
            r"polycyclic",
            r"polycyclische",
        ],
    ),
    (
        "non-pathogenic micro-organisms",
        [
            r"\bmou?ld(s|y|iness)?\b",
            r"\bschimmel",
            r"\byeast",
            r"\bgist(en|ing)\b",
            r"fermentat",
            r"\bspoil",
            r"\bbederf",
            r"enterobacteriaceae",
            r"coliform",
        ],
    ),
    (
        "parasitic infestation",
        [
            r"\binsect",
            r"\blarv",
            r"\bworms?\b",
            r"\bwormen\b",
            r"anisakis",
            r"parasit",
            r"infest",
            r"rodent",
            r"ongedierte",
            r"\bkevers?\b",
            r"\bmotten\b",
            r"\bmeelmot",
            r"\bmijten\b",
        ],
    ),
    (
        "chemical contamination (other)",
        [
            r"methanol",
            r"cleaning\s+(agent|solution|chemical|compound)",
            r"sanitizer",
            r"lubricant",
            r"hydraulic",
            r"fluid\s+from",
            r"\bchemical",
            r"chemische",
            r"schoonmaakmiddel",
            r"\bammonia",
            r"caustic",
            r"\bbleach",
        ],
    ),
    (
        "adulteration / fraud",
        [
            r"\bfraud",
            r"\bfraude",
            r"counterfeit",
            r"vervalst",
            r"\bsubstituted\b",
            r"\bsubstitution\b",
            r"porcine",
            r"varkens-?DNA",
        ],
    ),
    (
        "organoleptic aspects",
        [
            r"off[- ](odou?r|flavou?r|taste)",
            r"afwijkende?\s+(geur|smaak)",
            r"\bbad\s+(odou?r|taste|smell)",
            r"\brancid",
            r"\branzig",
            r"decompos",
        ],
    ),
    (
        "labelling absent/incomplete/incorrect",
        [
            r"mislabel",
            r"misbrand",
            r"\blabel(ing|ling)?\s+(does|did)\s+not",
            r"\blabel(ing|ling)?\s+(lacks?|missing|incorrect|error)",
            r"incorrect(ly)?\s+label",
            r"wrong\s+label",
            r"not\s+labell?ed",
            r"without\s+(english\s+)?label",
            r"nutrition\s+facts",
            r"(verkeerde?|onjuiste?|ontbrekende?)\s+(houdbaarheidsdatum|etiket|datum|THT|TGT)",
            r"houdbaarheidsdatum",
            r"geen\s+(houdbaarheidsdatum|THT|TGT|etiket)",
            r"inaccurate\w*\s+declared",
            r"nutrients?\s+(\w+\s+){0,3}?(overstated|understated)",
            r"niet\s+in\s+het\s+nederlands",
        ],
    ),
    (
        "poor or insufficient controls",
        [
            r"under-?process",
            r"pasteuri[sz]",
            r"insanitary",
            r"unsanitary",
            r"without\s+(an?\s+)?(\w+\s+)?licen[cs]e",
            r"not\s+registered",
            r"unregistered",
            r"temperature\s+abuse",
            r"niet\s+(goed\s+)?gekoeld",
            r"\bcgmp\b",
            r"good\s+manufacturing",
            r"lack(s|ing)?\s+(of\s+)?(\w+\s+)?records?\b",
            r"process(ing)?\s+deviation",
            r"restzuurstof",
            r"slecht\s+geseald",
            r"onvoldoende\s+(gegaard|verhit|gesteriliseerd|gepasteuriseerd|gekoeld)",
            r"not\s+properly\s+eviscerated",
            r"\b(not|improperly)\s+(stored|held|kept)\s+(under|at)\s+(\w+\s+){0,2}"
            r"(refrigerat|temperatur)",
        ],
    ),
    (
        "packaging defective / incorrect",
        [
            r"packag\w*\s+(defect|damage)",
            r"defect\w*\s+packag",
            r"prone\s+to\s+breakage",
            r"bottles?\s+(may|might|can)\s+(break|burst|explode)",
            r"verpakking\s+(is\s+)?(beschadigd|lek)",
            r"\bswollen\b",
            r"\bleak(ing|y)?\s+(\w+\s+)?(cans?|containers?|packages?)",
        ],
    ),
]

RULES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (category, re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE))
    for category, patterns in _RULES_SOURCE
)


def guess_hazard_category(text: str) -> str | None:
    """RASFF Hazard category name of the first matching rule, or None."""
    for category, pattern in RULES:
        if pattern.search(text):
            return category
    return None


# Snapshot fields that state the hazard (eval.snapshot); product descriptions and product
# lines mention ingredients and claims ("Preservative Free", "Non-GMO") that are not the
# recall reason, so they are only read when the hazard fields match nothing.
HAZARD_FIELDS = ("reason_for_recall", "title", "summary", "subject")


def guess_from_snapshot(snapshot: Mapping[str, str]) -> str | None:
    """Guess from the hazard-bearing fields first, then from the whole snapshot."""
    primary = "\n".join(v for k, v in snapshot.items() if k in HAZARD_FIELDS and v)
    return guess_hazard_category(primary) or guess_hazard_category(
        "\n".join(v for v in snapshot.values() if v)
    )
