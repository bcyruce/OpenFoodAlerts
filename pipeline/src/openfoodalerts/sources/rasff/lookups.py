"""RASFF Window dictionaries: numeric ID <-> name (spec §3.1).

The dictionaries are exported once into `db/seed/rasff/<dictionary>.json` and committed.
This module reads those seed files (the lookup API used by the parser), fetches the live
dictionaries, and diffs the two for `ofa seed-rasff-lookups`.

Seed file format (one file per dictionary, entries sorted by id, one entry per line)::

    {
      "dictionary": "hazard_categories",
      "endpoint": "hazardCategory/list/en/",
      "fetched_on": "2026-10-25",
      "entries": [
        {"id": 21782, "name": "biological contaminants"},
        ...
      ]
    }

Country entries also carry `"code"` (RASFF `alpha2Code`: ISO 3166-1 alpha-2, plus a few
organisations such as `ECDC`, `EUROPOL`, `OLAF`).
"""

import datetime as dt
import json
import os
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from functools import cache
from pathlib import Path
from typing import Any

from openfoodalerts.http import PoliteClient

BASE_URL = "https://webgate.ec.europa.eu/rasff-window/backend/public/"
REQUEST_INTERVAL = 3.0
SEED_DIR_ENV = "OFA_RASFF_SEED_DIR"
# `ofa seed-rasff-lookups` exit code when the live dictionaries differ from the seed files
# (1 is a crash or fetch error, 2 a usage error).
EXIT_DIFFERENCES = 3


class Dictionary(StrEnum):
    """A RASFF dictionary; the value is the seed file stem."""

    HAZARD_CATEGORY = "hazard_categories"
    PRODUCT_CATEGORY = "product_categories"
    NOTIFICATION_CLASSIFICATION = "notification_classifications"
    RISK_DECISION = "risk_decisions"
    PRODUCT_TYPE = "product_types"
    NOTIFICATION_BASIS = "notification_bases"
    ACTION_TAKEN = "actions_taken"
    COUNTRY = "countries"

    @property
    def endpoint(self) -> str:
        return _ENDPOINTS[self][0]

    @property
    def response_key(self) -> str:
        return _ENDPOINTS[self][1]


# (endpoint relative to BASE_URL, top-level key of the JSON response). Note that the
# productType endpoint answers under "notificationTypes".
_ENDPOINTS: dict[Dictionary, tuple[str, str]] = {
    Dictionary.HAZARD_CATEGORY: ("hazardCategory/list/en/", "hazardCategories"),
    Dictionary.PRODUCT_CATEGORY: ("productCategory/list/en/", "productCategories"),
    Dictionary.NOTIFICATION_CLASSIFICATION: (
        "notificationClassification/list/en/",
        "notificationClassifications",
    ),
    Dictionary.RISK_DECISION: ("riskDecision/list/en/", "riskDecisions"),
    Dictionary.PRODUCT_TYPE: ("productType/list/en/", "notificationTypes"),
    Dictionary.NOTIFICATION_BASIS: ("notificationBasis/list/en/", "notificationBasis"),
    Dictionary.ACTION_TAKEN: ("actionTaken/list/en/", "actionsTaken"),
    Dictionary.COUNTRY: ("country/list/", "countries"),
}


@dataclass(frozen=True, order=True)
class LookupEntry:
    """One dictionary entry. `code` is set for countries only."""

    id: int
    name: str
    code: str | None = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "name": self.name}
        if self.code is not None:
            out["code"] = self.code
        return out


class UnknownLookupValue(KeyError):
    """Raised when a name or id is not in a dictionary."""


class RasffLookupFetchError(RuntimeError):
    """A live dictionary could not be fetched or had an unexpected shape."""


def normalize_name(name: str) -> str:
    """Key used for name matching: case-insensitive, whitespace collapsed."""
    return " ".join(name.split()).casefold()


# --- parsing live responses -------------------------------------------------------


def parse_response(dictionary: Dictionary, payload: Any) -> list[LookupEntry]:
    """Turn one live dictionary response into entries sorted by id."""
    if not isinstance(payload, dict) or not isinstance(payload.get(dictionary.response_key), list):
        raise RasffLookupFetchError(
            f"{dictionary.endpoint}: expected an object with a {dictionary.response_key!r} list"
        )
    entries = []
    for item in payload[dictionary.response_key]:
        try:
            if dictionary is Dictionary.COUNTRY:
                entry = LookupEntry(
                    int(item["id"]), str(item["englishShortName"]), str(item["alpha2Code"])
                )
            else:
                entry = LookupEntry(int(item["id"]), str(item["description"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise RasffLookupFetchError(
                f"{dictionary.endpoint}: unexpected entry {item!r}"
            ) from exc
        entries.append(entry)
    return sorted(entries)


def fetch_dictionary(client: PoliteClient, dictionary: Dictionary) -> list[LookupEntry]:
    url = BASE_URL + dictionary.endpoint
    response = client.get(url)
    if response.status_code != 200:
        raise RasffLookupFetchError(f"GET {url}: HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise RasffLookupFetchError(f"GET {url}: response is not JSON") from exc
    return parse_response(dictionary, payload)


def fetch_all(client: PoliteClient) -> dict[Dictionary, list[LookupEntry]]:
    """Fetch every dictionary, sequentially (the client enforces the interval)."""
    return {d: fetch_dictionary(client, d) for d in Dictionary}


def make_client() -> PoliteClient:
    return PoliteClient(min_interval=REQUEST_INTERVAL)


# --- seed files ---------------------------------------------------------------------


def default_seed_dir() -> Path:
    """`db/seed/rasff/` in the repository, or $OFA_RASFF_SEED_DIR."""
    override = os.environ.get(SEED_DIR_ENV)
    if override:
        return Path(override)
    # lookups.py -> rasff -> sources -> openfoodalerts -> src -> pipeline -> repo root
    return Path(__file__).resolve().parents[5] / "db" / "seed" / "rasff"


def seed_path(dictionary: Dictionary, seed_dir: Path | None = None) -> Path:
    return (seed_dir or default_seed_dir()) / f"{dictionary.value}.json"


def read_seed(dictionary: Dictionary, seed_dir: Path | None = None) -> list[LookupEntry]:
    data = json.loads(seed_path(dictionary, seed_dir).read_text(encoding="utf-8"))
    return sorted(LookupEntry(int(e["id"]), str(e["name"]), e.get("code")) for e in data["entries"])


def render_seed(dictionary: Dictionary, entries: Iterable[LookupEntry], fetched_on: dt.date) -> str:
    """Seed file text: stable key order, entries sorted by id, one per line."""
    lines = [
        "{",
        f'  "dictionary": {json.dumps(dictionary.value)},',
        f'  "endpoint": {json.dumps(dictionary.endpoint)},',
        f'  "fetched_on": {json.dumps(fetched_on.isoformat())},',
        '  "entries": [',
    ]
    rendered = ["    " + json.dumps(e.to_json(), ensure_ascii=False) for e in sorted(entries)]
    lines.append(",\n".join(rendered))
    lines += ["  ]", "}"]
    return "\n".join(lines) + "\n"


def write_seed(
    dictionary: Dictionary,
    entries: Iterable[LookupEntry],
    fetched_on: dt.date,
    seed_dir: Path | None = None,
) -> Path:
    path = seed_path(dictionary, seed_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_seed(dictionary, entries, fetched_on), encoding="utf-8", newline="\n")
    return path


# --- lookup API ---------------------------------------------------------------------


@dataclass(frozen=True)
class Lookup:
    """Bidirectional id <-> name lookup for one dictionary."""

    dictionary: Dictionary
    entries: tuple[LookupEntry, ...]
    _by_id: Mapping[int, LookupEntry] = field(init=False, repr=False)
    _by_name: Mapping[str, LookupEntry] = field(init=False, repr=False)
    _by_code: Mapping[str, LookupEntry] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        by_id: dict[int, LookupEntry] = {}
        by_name: dict[str, LookupEntry] = {}
        by_code: dict[str, LookupEntry] = {}
        for e in self.entries:
            key = normalize_name(e.name)
            if e.id in by_id or key in by_name or (e.code and e.code.upper() in by_code):
                raise ValueError(f"{self.dictionary}: duplicate entry {e}")
            by_id[e.id] = e
            by_name[key] = e
            if e.code:
                by_code[e.code.upper()] = e
        object.__setattr__(self, "_by_id", by_id)
        object.__setattr__(self, "_by_name", by_name)
        object.__setattr__(self, "_by_code", by_code)

    def __iter__(self) -> Iterator[LookupEntry]:
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def get_by_id(self, rasff_id: int) -> LookupEntry | None:
        return self._by_id.get(rasff_id)

    def get_by_name(self, name: str) -> LookupEntry | None:
        """Match ignoring case and repeated whitespace."""
        return self._by_name.get(normalize_name(name))

    def get_by_code(self, code: str) -> LookupEntry | None:
        """Countries only: match on the RASFF `alpha2Code`/`isoCode`, case-insensitive."""
        return self._by_code.get(code.strip().upper())

    def name_for(self, rasff_id: int) -> str:
        entry = self.get_by_id(rasff_id)
        if entry is None:
            raise UnknownLookupValue(f"{self.dictionary}: unknown id {rasff_id}")
        return entry.name

    def id_for(self, name: str) -> int:
        entry = self.get_by_name(name)
        if entry is None:
            raise UnknownLookupValue(f"{self.dictionary}: unknown name {name!r}")
        return entry.id


@cache
def _cached_lookup(dictionary: Dictionary, seed_dir: Path) -> Lookup:
    return Lookup(dictionary, tuple(read_seed(dictionary, seed_dir)))


def lookup(dictionary: Dictionary, seed_dir: Path | None = None) -> Lookup:
    """The seeded dictionary as a `Lookup`; read once per process and cached."""
    return _cached_lookup(dictionary, (seed_dir or default_seed_dir()).resolve())


# --- diff ---------------------------------------------------------------------------


@dataclass
class DictionaryDiff:
    dictionary: Dictionary
    seed_count: int
    live_count: int
    added: list[LookupEntry] = field(default_factory=list)
    removed: list[LookupEntry] = field(default_factory=list)
    renamed: list[tuple[LookupEntry, LookupEntry]] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.renamed)


def diff_dictionary(
    dictionary: Dictionary, seed: Iterable[LookupEntry], live: Iterable[LookupEntry]
) -> DictionaryDiff:
    """Compare by id: new ids are added, missing ids removed, changed name/code renamed."""
    seed_by_id = {e.id: e for e in seed}
    live_by_id = {e.id: e for e in live}
    diff = DictionaryDiff(dictionary, len(seed_by_id), len(live_by_id))
    for rasff_id in sorted(seed_by_id.keys() | live_by_id.keys()):
        old, new = seed_by_id.get(rasff_id), live_by_id.get(rasff_id)
        if old is None and new is not None:
            diff.added.append(new)
        elif new is None and old is not None:
            diff.removed.append(old)
        elif old is not None and new is not None and old != new:
            diff.renamed.append((old, new))
    return diff


def _describe(entry: LookupEntry) -> str:
    code = f" [{entry.code}]" if entry.code is not None else ""
    return f"{entry.id} {entry.name!r}{code}"


def format_report(diffs: Iterable[DictionaryDiff]) -> str:
    lines: list[str] = []
    changed = 0
    for d in diffs:
        if not d.has_changes:
            lines.append(f"{d.dictionary}: identical ({d.live_count} entries)")
            continue
        changed += 1
        lines.append(f"{d.dictionary}: CHANGED (seed {d.seed_count}, live {d.live_count})")
        lines += [f"  + added    {_describe(e)}" for e in d.added]
        lines += [f"  - removed  {_describe(e)}" for e in d.removed]
        lines += [f"  ~ renamed  {_describe(o)} -> {_describe(n)}" for o, n in d.renamed]
    lines.append("")
    if changed:
        lines.append(
            f"{changed} dictionary(ies) differ from db/seed/rasff/. Nothing was written. "
            "Review the changes (and their effect on the taxonomy, ticket 11) before "
            "regenerating the seed files with `ofa export-rasff-lookups`."
        )
    else:
        lines.append("All RASFF dictionaries match db/seed/rasff/.")
    return "\n".join(lines)


def check_against_seed(client: PoliteClient, seed_dir: Path | None = None) -> list[DictionaryDiff]:
    """Fetch the live dictionaries and diff each against its seed file. Read-only."""
    live = fetch_all(client)
    return [diff_dictionary(d, read_seed(d, seed_dir), live[d]) for d in Dictionary]


def export_seeds(
    client: PoliteClient, seed_dir: Path | None = None, today: dt.date | None = None
) -> dict[Dictionary, int]:
    """Fetch the live dictionaries and (re)write the seed files. Returns entry counts."""
    fetched_on = today or dt.date.today()
    counts = {}
    for d, entries in fetch_all(client).items():
        write_seed(d, entries, fetched_on, seed_dir)
        counts[d] = len(entries)
    return counts
