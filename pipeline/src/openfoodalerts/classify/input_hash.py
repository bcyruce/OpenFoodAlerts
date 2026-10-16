"""`input_hash` of an AI classification (spec §6.3).

input_hash = sha256(normalized input + prompt_version + model + taxonomy_version), where the
normalized input is the model input (the frozen snapshot of eval/README.md, keys in their
order) as compact JSON with every string NFC-normalized. Nothing else is changed, because
`evidence_span` must stay a substring of the input. The parts are joined with newlines.

Both the classifier (ticket 16, `ai_classifications.input_hash` and the eval cache) and the
eval harness (to spot cached outputs whose input has changed) use this function; changing it
invalidates every cache.
"""

import hashlib
import json
import unicodedata
from collections.abc import Mapping


def normalized_input(snapshot: Mapping[str, str]) -> str:
    return json.dumps(
        {key: unicodedata.normalize("NFC", value) for key, value in snapshot.items()},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def input_hash(
    snapshot: Mapping[str, str], *, prompt_version: str, model: str, taxonomy_version: str
) -> str:
    text = "\n".join((normalized_input(snapshot), prompt_version, model, taxonomy_version))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
