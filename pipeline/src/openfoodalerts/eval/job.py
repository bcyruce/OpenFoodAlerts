"""`ofa eval-sample` and `ofa eval-exclude`: build the eval set and write it out.

Outputs (in `eval/`): `items.csv`, `labels.csv` (header only until labelling starts),
`exclusions.csv` (replayed on every run), `sampling.json` (parameters and counts), plus
the `eval_items` table. A run never drops an item that already has Labels unless forced.
"""

import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

from openfoodalerts.db.connection import Connection
from openfoodalerts.eval.files import (
    Exclusion,
    ensure_labels_file,
    read_exclusions,
    read_labels,
    write_exclusions,
    write_items,
)
from openfoodalerts.eval.frame import FrameConfig, load_frame
from openfoodalerts.eval.labelset import Taxonomy, load_taxonomy
from openfoodalerts.eval.sampling import (
    UNMATCHED,
    Candidate,
    EvalItem,
    EvalSet,
    SamplingConfig,
    build_eval_set,
    deduplicate,
)

REPO_ROOT = Path(__file__).resolve().parents[4]


def default_eval_dir() -> Path:
    return REPO_ROOT / "eval"


class EvalSetChanged(RuntimeError):
    """The new sample would drop items that already have Labels."""


def _repo_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.name


def summarize(
    result: EvalSet,
    frame: Sequence[Candidate],
    taxonomy: Taxonomy,
    taxonomy_path: Path,
    config: SamplingConfig,
    frame_config: FrameConfig,
) -> dict[str, Any]:
    """Parameters and counts of a run (sampling.json); no timestamps, so reruns match."""
    strata = Counter(c.stratum for c in deduplicate(frame, config.seed))
    items = result.items
    return {
        "seed": config.seed,
        "taxonomy": {"path": _repo_path(taxonomy_path), "version": taxonomy.version},
        "frame": frame_config.describe(),
        "quotas": dict(config.quotas),
        "min_per_label": config.min_per_label,
        "frame_sizes": dict(sorted(strata.items())),
        "allocation": {
            f"{s}:{g or UNMATCHED}": n for (s, g), n in sorted(result.allocation.items(), key=str)
        },
        "label_counts": {
            label: sum(1 for i in items if i.candidate.group == label) for label in taxonomy.labels
        }
        | {UNMATCHED: sum(1 for i in items if i.candidate.group is None)},
        "shortfall": result.shortfall,
        "splits": {
            f"{s}:{split}": n
            for (s, split), n in sorted(Counter((i.source, i.split) for i in items).items())
        },
        "noise_audit": sum(i.noise_audit for i in items),
        "agreement": sum(i.agreement for i in items),
        "replacements": [
            {"excluded": r.excluded, "replaced_by": r.replaced_by} for r in result.replacements
        ],
        "unknown_exclusions": result.unknown_exclusions,
    }


def _store(conn: Connection, items: Sequence[EvalItem], result: EvalSet, version: str) -> None:
    """Mirror the set into eval_items (rows with Labels are updated, never deleted)."""
    conn.execute("UPDATE eval_items SET replaced_by = NULL")
    conn.execute(
        "DELETE FROM eval_items e WHERE NOT EXISTS"
        " (SELECT 1 FROM eval_labels l WHERE l.eval_item_id = e.id)"
    )
    rows = [(i, "active") for i in items] + [(r.item, "excluded") for r in result.replacements]
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO eval_items (id, notification_id, source_code, split, noise_audit,
                agreement, stratum, input_snapshot, status, taxonomy_version)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET notification_id = EXCLUDED.notification_id,
                split = EXCLUDED.split, noise_audit = EXCLUDED.noise_audit,
                agreement = EXCLUDED.agreement, stratum = EXCLUDED.stratum,
                input_snapshot = EXCLUDED.input_snapshot, status = EXCLUDED.status,
                taxonomy_version = EXCLUDED.taxonomy_version
            """,
            [
                (
                    i.item_id,
                    i.candidate.notification_id,
                    i.source,
                    i.split,
                    i.noise_audit,
                    i.agreement,
                    i.stratum,
                    Jsonb(dict(i.candidate.snapshot)),
                    status,
                    version,
                )
                for i, status in rows
            ],
        )
        cur.executemany(
            "UPDATE eval_items SET replaced_by = %s WHERE id = %s",
            [(r.replaced_by, r.excluded) for r in result.replacements if r.replaced_by],
        )


def run_sampling(
    conn: Connection,
    *,
    taxonomy_path: Path,
    eval_dir: Path,
    config: SamplingConfig | None = None,
    frame_config: FrameConfig | None = None,
    force: bool = False,
) -> tuple[EvalSet, dict[str, Any]]:
    config = config or SamplingConfig()
    frame_config = frame_config or FrameConfig()
    taxonomy = load_taxonomy(taxonomy_path)
    frame = load_frame(conn, taxonomy, frame_config)
    exclusions = read_exclusions(eval_dir / "exclusions.csv")
    result = build_eval_set(frame, taxonomy.labels, config, [e.item_id for e in exclusions])

    keep = {i.item_id for i in result.items} | {e.item_id for e in exclusions}
    labelled = {r["item_id"] for r in read_labels(eval_dir / "labels.csv")}
    lost = sorted(labelled - keep)
    if lost and not force:
        raise EvalSetChanged(
            f"{len(lost)} labelled items would leave the eval set: {', '.join(lost[:10])}"
            " (re-run with --force to accept)"
        )

    summary = summarize(result, frame, taxonomy, taxonomy_path, config, frame_config)
    write_items(eval_dir / "items.csv", result.items)
    ensure_labels_file(eval_dir / "labels.csv")
    replaced = {r.excluded: r.replaced_by for r in result.replacements}
    if exclusions:
        write_exclusions(
            eval_dir / "exclusions.csv",
            [Exclusion(e.item_id, e.reason, replaced.get(e.item_id)) for e in exclusions],
        )
    (eval_dir / "sampling.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    _store(conn, result.items, result, taxonomy.version)
    conn.commit()
    return result, summary


def non_food_items(eval_dir: Path) -> list[str]:
    """Items whose latest Label (any annotator) says non-food, in labels.csv order."""
    latest: dict[tuple[str, str], str] = {}
    for row in read_labels(eval_dir / "labels.csv"):
        latest[(row["item_id"], row["annotator"])] = row["product_type"]
    return list(dict.fromkeys(item for (item, _), value in latest.items() if value == "non-food"))


def exclude_items(
    conn: Connection,
    item_ids: Sequence[str],
    *,
    reason: str,
    taxonomy_path: Path,
    eval_dir: Path,
    config: SamplingConfig | None = None,
    frame_config: FrameConfig | None = None,
) -> tuple[EvalSet, dict[str, Any]]:
    """Record exclusions (appended in order, duplicates ignored) and rebuild the set."""
    path = eval_dir / "exclusions.csv"
    existing = read_exclusions(path)
    known = {e.item_id for e in existing}
    added = [Exclusion(i, reason) for i in dict.fromkeys(item_ids) if i not in known]
    write_exclusions(path, existing + added)
    return run_sampling(
        conn,
        taxonomy_path=taxonomy_path,
        eval_dir=eval_dir,
        config=config,
        frame_config=frame_config,
    )
