"""Rule part of Product type (spec §4.2). Rules decide only clear cases; the rest wait for T5."""

import re

from openfoodalerts.parse.model import ProductType

_FEED = re.compile(
    r"\b(pet food|animal feed|(dog|cat|pet|puppy|kitten|bird|horse)s?\W+(\w+\W+){0,3}?"
    r"(food|treats?|chews?|kibble|feed|diet))\b",
    re.IGNORECASE,
)
_NON_FOOD = re.compile(
    r"\b(cosmetics?|shampoo|hair conditioner|lotion|deodorant|sunscreen|toothpaste|mouthwash"
    r"|hand sanitizer|(hand|bar|liquid) soap|perfume|nail polish)\b",
    re.IGNORECASE,
)


def openfda_product_type(product_description: str) -> ProductType | None:
    """Return the rule decision for an FDA food enforcement product, or None for "ask T5".

    The default is food (supplements count as food, as in RASFF).
    """
    hits: set[ProductType] = set()
    if _FEED.search(product_description):
        hits.add("feed")
    if _NON_FOOD.search(product_description):
        hits.add("non-food")
    if len(hits) > 1:
        return None
    return hits.pop() if hits else "food"


# NVWA (Dutch). Each pattern names one kind of product; a warning decided by the rules must
# hit exactly one of them, and only food and non-food are decided here: food contact
# materials, feed and every conflict wait for T5 (spec §4.2). Patterns are checked against
# the title, the summary paragraph and the product lines, never against ingredient lists.
def _words(*alternatives: str) -> re.Pattern[str]:
    return re.compile(r"\b(" + "|".join(alternatives) + r")\b", re.IGNORECASE)


_NVWA_NON_FOOD = _words(
    # children and babies
    r"(kinder|baby|auto|fiets)(zitje|zitjes|stoel|stoelen|stoeltje)\w*",
    r"autostoel\w*",
    r"kinderwagen\w*",
    r"wandelwagen\w*",
    r"buggy\w*",
    r"draagzak\w*",
    r"slaapzak\w*",
    r"romper\w*",
    r"\w*speelgoed\w*",
    r"pluche\w*",
    r"poppen",
    r"speel(kleed|toestel)\w*",
    r"marionet\w*",
    r"waterballon\w*",
    r"knuffel\w*",
    r"rammelaar\w*",
    r"bijtring\w*",
    r"speen",
    r"spenen",
    r"bordspel\w*",
    r"puzzel\w*",
    r"magneetbal\w*",
    r"magnetisch\w*",
    r"slijm",
    r"kneed\w*",
    r"boek(je|jes|en)?",
    r"stretch\w*",
    r"squish\w*",
    r"pufferfigu\w*",
    r"speelset\w*",
    r"bouwstenen",
    r"\w*zand",
    r"sand",
    r"\w*schommel(s)?",
    r"speenkoord\w*",
    r"fopspe\w*",
    # electrical
    r"\w*powerbank\w*",
    r"\w*power bank\w*",
    r"oplader\w*",
    r"\w*lader",
    r"laadkabel\w*",
    r"\w*adapter(s)?",
    r"\w*contactdoos",
    r"lichtsnoer\w*",
    r"zonnepane\w*",
    r"stijltang\w*",
    r"krultang\w*",
    r"föhn\w*",
    r"batterij\w*",
    r"accu\w*",
    r"stekker\w*",
    r"verlengsnoer\w*",
    r"stroomhaspel\w*",
    r"\w*ventilator\w*",
    r"kachel\w*",
    r"bureauonderlegger\w*",
    r"stofzuiger\w*",
    r"vloerenreiniger\w*",
    r"lamp(en|je|jes)?",
    r"rookmelder\w*",
    r"\w*droger(s)?",
    r"\w*scooter\w*",
    # clothing, accessories, cosmetics
    r"kleding\w*",
    r"\w*jurk(en|je|jes)?",
    r"(kinder|baby|reddings|zwem|veiligheids)?vest(je|jes|en)?",
    r"\w*jas(je|jes|sen)?",
    r"jacket\w*",
    r"\w*sweater\w*",
    r"trui(en|tje|tjes)?",
    r"pyjama\w*",
    r"boxpak\w*",
    r"piercing\w*",
    r"\w*slipper\w*",
    r"\w*schoen(en)?",
    r"\w*handschoen\w*",
    r"portemonne\w*",
    r"handtas\w*",
    r"rugzak\w*",
    r"sieraad",
    r"sieraden",
    r"ketting\w*",
    r"armband\w*",
    r"oorbel\w*",
    r"cosmetica",
    r"shampoo\w*",
    r"zonnebrand\w*",
    r"tandpasta\w*",
    r"floss\w*",
    r"tandzijde",
    r"tandenborstel\w*",
    r"deodorant\w*",
    r"nagellak\w*",
    r"nail art",
    r"make[- ]?up",
    r"parfum\w*",
    r"eau de toilette",
    r"horloge\w*",
    # sport, tools, other
    r"karabiner\w*",
    r"klimgordel\w*",
    r"\w*fiets(en)?",
    r"fietsendrager\w*",
    r"e-bike\w*",
    r"(fiets|ski|ruiter|motor|klim|mtb)?helm(en)?",
    r"kettlebell\w*",
    r"badminton\w*",
    r"basketbal\w*",
    r"klimtouw\w*",
    r"luchtdrukpisto\w*",
    r"asbak\w*",
    r"fluitje(s)?",
    r"gasbarbecue\w*",
    r"\w*gereedschap\w*",
    r"boormachine\w*",
    r"grasmaaier\w*",
    r"aansteker\w*",
    r"vuurwerk",
    r"e-sigaret\w*",
    r"\w*kaars(en)?",
    r"lijm\w*",
    r"ijsbijl\w*",
    r"klimanker\w*",
    r"skistok\w*",
)
_NVWA_FOOD_CONTACT = _words(
    r"\w*molen(s)?",
    r"(braad|koeken|wok|steel|grill|kook|soep|bak)?pan(nen)?",
    r"servies\w*",
    r"beker(s|tje|tjes)?",
    r"mok(ken)?",
    r"drinkfles\w*",
    r"babyfles\w*",
    r"lunchbox\w*",
    r"bewaardoos\w*",
    r"bestek",
    r"snijplank\w*",
    r"keukengerei",
    r"spatel\w*",
    r"theepot\w*",
    r"waterkoker\w*",
    r"contactgrill\w*",
    r"airfryer\w*",
    r"blender\w*",
    r"rietje(s)?",
    r"bakvorm\w*",
)
_NVWA_FEED = _words(
    r"honden\w*",
    r"katten\w*",
    r"hond",
    r"kat",
    r"huisdier\w*",
    r"diervoed\w*",
    r"dierenvoe\w*",
    r"kauwsnack\w*",
    r"kauwbot\w*",
    r"paardenvoer\w*",
    r"vogelvoer\w*",
)
_FOOD_ALLERGENS = (
    r"(ei|eieren|melk|koemelk|lactose|pinda\w*|noten|gluten|tarwe|soja|sesam\w*|selderij"
    r"|mosterd|lupine|vis|schaaldieren|kreeftachtigen|garnalen|weekdieren|sulfiet\w*"
    r"|amandel\w*|hazelno\w*|cashew\w*|walno\w*|pistache\w*|pecan\w*|macadamia\w*)"
)
_NVWA_FOOD = re.compile(
    r"\b("
    # consumption advice, as NVWA words it: "Eet het product niet", "Drink het niet"
    r"(eet|drink|eten|drinken|nuttig|consumeer)\b[^.!?\n]{0,80}\bniet"
    # food-borne pathogens and toxins, residues
    r"|salmonella|listeria|e\.\s?coli|stec|norovirus|hepatitis a|bacillus cereus|cereulide"
    r"|botulisme|clostridium|campylobacter|aflatoxine\w*|ochratoxine\w*|ethyleenoxide|histamine"
    r"|pesticide\w*|bestrijdingsmiddel\w*"
    # food allergens
    r"|allergenen|allergisch\s+(bent\s+)?voor\s+(\w+[\s,]+){0,4}?" + _FOOD_ALLERGENS + r""
    r"|" + _FOOD_ALLERGENS + r"[- ]?allergie"
    r"|(gluten|lactose)-?intoleran\w*"
    r")\b",
    re.IGNORECASE,
)


# The keyword patterns per Product type (also used by the fake model's T5 answers).
NVWA_PATTERNS: tuple[tuple[ProductType, re.Pattern[str]], ...] = (
    ("non-food", _NVWA_NON_FOOD),
    ("food contact material", _NVWA_FOOD_CONTACT),
    ("feed", _NVWA_FEED),
    ("food", _NVWA_FOOD),
)
OPENFDA_PATTERNS: tuple[tuple[ProductType, re.Pattern[str]], ...] = (
    ("non-food", _NON_FOOD),
    ("feed", _FEED),
)


def nvwa_product_type(
    title: str, summary: str | None, product_text: str | None
) -> ProductType | None:
    """Return "food" or "non-food" when the rules are sure, else None ("ask T5")."""
    text = "\n".join(t for t in (title, summary, product_text) if t)
    hits = {kind for kind, pattern in NVWA_PATTERNS if pattern.search(text)}
    if hits == {"food"}:
        return "food"
    if hits == {"non-food"}:
        return "non-food"
    return None
