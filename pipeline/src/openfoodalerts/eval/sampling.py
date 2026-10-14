"""Plan the hand-labelled eval set (spec §7.1, ticket 12). Pure functions, no database.

Input: the sampling frame, one `Candidate` per eligible Notification with its pre-label
"hazard group" (official RASFF category or the keyword guess, mapped to a T1 label; None
when nothing matched). Output: 300 `EvalItem`s, reproducible from the frame and the seed.

1. Order: every candidate gets a rank, sha256(seed | source | source_key). Ranks do not
   depend on the order the frame is read in, so the same frame and seed give the same
   sample on any machine.
2. Clusters: candidates sharing a cluster (an FDA recall event lists every product of one
   recall separately) are reduced to the lowest-ranked one, so a stratum is not filled with
   near-identical copies.
3. Allocation per Source x group:
   a. proportional: each Source's quota is spread over its groups in proportion to their
      size in the frame (largest remainder), unmatched texts included, so each Source's
      sample starts out representative;
   b. label floors: round-robin over the T1 labels (least represented first), one item per
      label per round until each label has `min_per_label` items. The item comes from the
      Source where the label is relatively most common (share of that Source's frame) and
      replaces one item of that Source's largest stratum (never one that would drop
      another label below its floor). Floors may take at most `floor_share` of a Source's
      quota: 40% for NVWA and FDA, so their common hazards stay well represented, 100% for
      RASFF, whose official categories make it the natural supplier of rare labels.
   Labels still below the floor are reported as shortfall. `sampling.json` records the
   frame size and allocation of every stratum, so metrics can be reweighted to the frame.
4. Within a stratum the lowest ranks are taken.
5. Splits per Source: items ordered by (stratum, rank) and every third one goes to dev, so
   dev and test have the same strata mix (NVWA 40/80, FDA 40/80, RASFF 20/40). The
   agreement subset (second annotator) is picked the same way with a second rank (1 in 5).
   All RASFF items form the noise audit set.
6. Exclusions: an item found to be non-food while labelling is replaced by the next ranked
   unused candidate of its stratum (else of its Source), which inherits its split and flags.
   Exclusions are replayed in order on every run, so the final set stays reproducible.
"""

import hashlib
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date

SOURCES = ("nvwa", "openfda", "rasff")
ID_PREFIX = {"nvwa": "nv", "openfda": "fd", "rasff": "ra"}
UNMATCHED = "unmatched"
DEFAULT_SEED = 20261025
DEFAULT_QUOTAS: Mapping[str, int] = {"nvwa": 120, "openfda": 120, "rasff": 60}
DEFAULT_FLOOR_SHARE: Mapping[str, float] = {"nvwa": 0.4, "openfda": 0.4, "rasff": 1.0}


def item_id(source: str, source_key: str) -> str:
    return f"{ID_PREFIX[source]}-{hashlib.sha256(source_key.encode()).hexdigest()[:8]}"


def rank(seed: int | str, source: str, source_key: str) -> str:
    return hashlib.sha256(f"{seed}|{source}|{source_key}".encode()).hexdigest()


@dataclass(frozen=True)
class Candidate:
    source: str
    source_key: str
    notification_id: int
    # T1 label of the official category (RASFF) or of the keyword guess; None = no match
    group: str | None
    snapshot: Mapping[str, str]
    published_on: date | None
    source_url: str
    # RASFF official Hazard category names (noise audit reference)
    official_categories: tuple[str, ...] = ()
    # candidates of one cluster (FDA recall event) count once
    cluster: str | None = None

    @property
    def stratum(self) -> str:
        return f"{self.source}:{self.group or UNMATCHED}"


@dataclass(frozen=True)
class EvalItem:
    item_id: str
    candidate: Candidate
    split: str
    noise_audit: bool
    agreement: bool

    @property
    def source(self) -> str:
        return self.candidate.source

    @property
    def stratum(self) -> str:
        return self.candidate.stratum


@dataclass(frozen=True)
class SamplingConfig:
    seed: int = DEFAULT_SEED
    quotas: Mapping[str, int] = field(default_factory=lambda: dict(DEFAULT_QUOTAS))
    min_per_label: int = 8
    # share of a Source's quota that label floors may take from its proportional sample
    floor_share: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_FLOOR_SHARE))
    dev_fraction: tuple[int, int] = (1, 3)  # dev 100 of 300
    agreement_fraction: tuple[int, int] = (1, 5)  # 60 of 300


@dataclass(frozen=True)
class Replacement:
    excluded: str
    replaced_by: str | None
    item: EvalItem  # the excluded item


@dataclass
class EvalSet:
    items: list[EvalItem]
    # (source, group or None) -> items allocated
    allocation: dict[tuple[str, str | None], int]
    # label -> items missing to reach the floor
    shortfall: dict[str, int]
    replacements: list[Replacement] = field(default_factory=list)
    # exclusions whose item is not in the set (the frame changed)
    unknown_exclusions: list[str] = field(default_factory=list)


Stratum = tuple[str, str | None]


def deduplicate(candidates: Iterable[Candidate], seed: int) -> list[Candidate]:
    """Keep one candidate per (source, cluster) and per (source, key); sorted by rank."""
    best: dict[tuple[str, str], tuple[str, Candidate]] = {}
    for c in candidates:
        key = (c.source, f"cluster:{c.cluster}" if c.cluster else f"key:{c.source_key}")
        r = rank(seed, c.source, c.source_key)
        if key not in best or r < best[key][0]:
            best[key] = (r, c)
    return [c for _, c in sorted(best.values(), key=lambda rc: rc[0])]


def _largest_remainder(total: int, weights: Mapping[str | None, int]) -> dict[str | None, int]:
    """Split `total` (<= sum of weights) in proportion to weights; ties by group name."""
    weight_sum = sum(weights.values())
    if total >= weight_sum:
        return dict(weights)
    shares = {g: total * w / weight_sum for g, w in weights.items()}
    out = {g: int(s) for g, s in shares.items()}
    left = total - sum(out.values())
    by_fraction = sorted(weights, key=lambda g: (-(shares[g] - out[g]), g or ""))
    for g in by_fraction[:left]:
        out[g] += 1
    return out


def allocate(
    available: Mapping[Stratum, int],
    quotas: Mapping[str, int],
    labels: Sequence[str],
    min_per_label: int,
    floor_share: Mapping[str, float],
) -> tuple[dict[Stratum, int], dict[str, int]]:
    """Items per (source, group) and the label shortfall (module docstring, step 3)."""
    taken: dict[Stratum, int] = defaultdict(int)
    size = {s: sum(n for (src, _), n in available.items() if src == s) for s in quotas}
    for source in quotas:
        weights = {g: n for (s, g), n in available.items() if s == source and n > 0}
        for group, n in _largest_remainder(quotas[source], weights).items():
            taken[(source, group)] = n
    budget = {s: int(quotas[s] * floor_share.get(s, 1.0)) for s in quotas}

    def spare(stratum: Stratum) -> int:
        return available.get(stratum, 0) - taken[stratum]

    def label_total(label: str | None) -> int:
        return sum(taken[(s, label)] for s in quotas)

    def donor(source: str, label: str) -> Stratum | None:
        """The stratum of `source` most over-sampled relative to its frame size (so the rest
        stays proportional) that can give an item up without dropping a label floor."""
        options = [
            (s, g)
            for (s, g), n in taken.items()
            if s == source
            and n > 0
            and g != label
            and (g is None or g not in labels or label_total(g) > min_per_label)
        ]
        return max(
            options,
            key=lambda st: (taken[st] / available[st], taken[st], st[1] or ""),
            default=None,
        )

    def relative(source: str, label: str) -> float:
        return available.get((source, label), 0) / size[source] if size[source] else 0.0

    order = sorted(labels, key=lambda label: (label_total(label), labels.index(label)))
    for _ in range(min_per_label):
        progress = False
        for label in order:
            if label_total(label) >= min_per_label:
                continue
            for source in sorted(quotas, key=lambda s: (-relative(s, label), s)):
                if budget[source] <= 0 or spare((source, label)) <= 0:
                    continue
                full = sum(taken[(s, g)] for (s, g) in list(taken) if s == source) >= quotas[source]
                give = donor(source, label) if full else None
                if full and give is None:
                    continue
                if give is not None:
                    taken[give] -= 1
                taken[(source, label)] += 1
                budget[source] -= 1
                progress = True
                break
        if not progress:
            break

    shortfall = {
        label: min_per_label - label_total(label)
        for label in labels
        if label_total(label) < min_per_label
    }
    return {k: v for k, v in taken.items() if v}, shortfall


def _evenly_spaced(n: int, k: int) -> set[int]:
    """k of n positions, spread evenly (position i is picked when floor((i+1)k/n) steps)."""
    return {i for i in range(n) if ((i + 1) * k) // n > (i * k) // n}


def _fraction(n: int, fraction: tuple[int, int]) -> int:
    num, den = fraction
    return (n * num + den // 2) // den


def _assign(selected: Sequence[Candidate], config: SamplingConfig) -> list[EvalItem]:
    items = []
    for source in SOURCES:
        mine = [c for c in selected if c.source == source]
        by_rank = sorted(mine, key=lambda c: (c.stratum, rank(config.seed, source, c.source_key)))
        dev = _evenly_spaced(len(by_rank), _fraction(len(by_rank), config.dev_fraction))
        agreement_seed = f"{config.seed}:agreement"
        by_second = sorted(
            mine, key=lambda c: (c.stratum, rank(agreement_seed, source, c.source_key))
        )
        picked = _evenly_spaced(len(mine), _fraction(len(mine), config.agreement_fraction))
        agreement = {by_second[i].source_key for i in picked}
        for i, c in enumerate(by_rank):
            items.append(
                EvalItem(
                    item_id=item_id(source, c.source_key),
                    candidate=c,
                    split="dev" if i in dev else "test",
                    noise_audit=source == "rasff",
                    agreement=c.source_key in agreement,
                )
            )
    return order_items(items, config.seed)


def order_items(items: Iterable[EvalItem], seed: int) -> list[EvalItem]:
    """Labelling order: dev before test, shuffled by rank within a split."""
    return sorted(
        items,
        key=lambda i: (i.split != "dev", rank(seed, i.source, i.candidate.source_key)),
    )


def build_eval_set(
    candidates: Iterable[Candidate],
    labels: Sequence[str],
    config: SamplingConfig,
    exclusions: Sequence[str] = (),
) -> EvalSet:
    """Sample the eval set from the frame, then replay the exclusions (item ids) in order."""
    frame = [c for c in deduplicate(candidates, config.seed) if c.source in config.quotas]
    by_stratum: dict[Stratum, list[Candidate]] = defaultdict(list)
    for c in frame:  # already in rank order
        by_stratum[(c.source, c.group)].append(c)
    available = {s: len(cs) for s, cs in by_stratum.items()}
    allocation, shortfall = allocate(
        available, config.quotas, labels, config.min_per_label, config.floor_share
    )
    selected = [
        c for s, n in sorted(allocation.items(), key=_stratum_key) for c in by_stratum[s][:n]
    ]
    result = EvalSet(_assign(selected, config), allocation, shortfall)
    for excluded in exclusions:
        _replace(result, excluded, frame, config)
    return result


def _stratum_key(item: tuple[Stratum, int]) -> tuple[str, str]:
    (source, group), _ = item
    return (source, group or "")


def _replace(
    result: EvalSet, excluded: str, frame: Sequence[Candidate], config: SamplingConfig
) -> None:
    current = {i.item_id: i for i in result.items}
    if excluded not in current:
        result.unknown_exclusions.append(excluded)
        return
    old = current[excluded]
    used = set(current) | {r.excluded for r in result.replacements}
    same_source = [
        c for c in frame if c.source == old.source and item_id(c.source, c.source_key) not in used
    ]
    same_stratum = [c for c in same_source if c.stratum == old.stratum]
    pool = same_stratum or same_source
    items = [i for i in result.items if i.item_id != excluded]
    new_id = None
    if pool:
        new = replace(old, item_id=item_id(old.source, pool[0].source_key), candidate=pool[0])
        new_id = new.item_id
        items.append(new)
    result.items = order_items(items, config.seed)
    result.replacements.append(Replacement(excluded, new_id, old))
