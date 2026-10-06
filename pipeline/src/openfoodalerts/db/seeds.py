"""Load the committed seed files (db/seed/) into the database. Idempotent upserts.

Only the columns that come from the seed are written: translations (`name_nl`,
`name_zh`) and the taxonomy columns of `hazard_categories` (`label`,
`taxonomy_version`, ticket 11) are never touched. Rows whose RASFF id disappeared from
a seed file are kept, because Notifications may still reference them;
`ofa seed-rasff-lookups` reports such removals.

The caller owns the transaction (the CLI commits; tests roll back).
"""

from pathlib import Path

from openfoodalerts.db.connection import Connection
from openfoodalerts.sources.rasff.lookups import Dictionary, read_seed

_UPSERT_COUNTRY = """
INSERT INTO countries (iso2, rasff_id, name_en) VALUES (%s, %s, %s)
ON CONFLICT (iso2) DO UPDATE SET rasff_id = EXCLUDED.rasff_id, name_en = EXCLUDED.name_en
"""

_UPSERT_BY_RASFF_ID = """
INSERT INTO {table} (rasff_id, name_en) VALUES (%s, %s)
ON CONFLICT (rasff_id) DO UPDATE SET name_en = EXCLUDED.name_en
"""

# table -> RASFF dictionary it is seeded from (other dictionaries have no table)
_CATEGORY_TABLES = {
    "hazard_categories": Dictionary.HAZARD_CATEGORY,
    "product_categories": Dictionary.PRODUCT_CATEGORY,
}


def load_seeds(conn: Connection, rasff_seed_dir: Path | None = None) -> dict[str, int]:
    """Upsert every seed table; returns the number of seed rows per table."""
    counts: dict[str, int] = {}
    with conn.cursor() as cur:
        countries = read_seed(Dictionary.COUNTRY, rasff_seed_dir)
        cur.executemany(_UPSERT_COUNTRY, [(c.code, c.id, c.name) for c in countries])
        counts["countries"] = len(countries)
        for table, dictionary in _CATEGORY_TABLES.items():
            entries = read_seed(dictionary, rasff_seed_dir)
            cur.executemany(
                _UPSERT_BY_RASFF_ID.format(table=table), [(e.id, e.name) for e in entries]
            )
            counts[table] = len(entries)
    return counts
