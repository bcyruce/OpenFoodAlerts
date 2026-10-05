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
