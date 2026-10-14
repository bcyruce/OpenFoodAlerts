"""The eval-set planner: stratified, reproducible, with label floors, splits and flags."""

import zlib
from collections import Counter
from datetime import date

from openfoodalerts.eval.sampling import (
    Candidate,
    EvalItem,
    SamplingConfig,
    build_eval_set,
    item_id,
)

LABELS = ("pathogenic micro-organisms", "allergens", "foreign bodies", "TSEs", "radiation", "other")


def cand(source: str, key: str, group: str | None, cluster: str | None = None) -> Candidate:
    return Candidate(
        source=source,
        source_key=key,
        notification_id=zlib.crc32(f"{source}|{key}".encode()),
        group=group,
        snapshot={"text": key},
        published_on=date(2025, 1, 1),
        source_url=f"https://example.org/{key}",
        cluster=cluster,
    )


def pool() -> list[Candidate]:
    """NVWA and FDA have the common hazards; only RASFF has TSEs and radiation."""
    out = []
    for i in range(300):
        out.append(cand("nvwa", f"/n/{i}", ["allergens", "foreign bodies", None][i % 3]))
    for i in range(600):
        group = ["pathogenic micro-organisms", "allergens", "foreign bodies", "other", None][i % 5]
        out.append(cand("openfda", f"F-{i}", group))
    for i in range(200):
        out.append(
            cand(
                "rasff", f"2025.{i:04}", ["pathogenic micro-organisms", "TSEs", "radiation"][i % 3]
            )
        )
    return out


def by_source(items: list[EvalItem]) -> Counter[str]:
    return Counter(i.source for i in items)


def test_source_quotas_are_met() -> None:
    result = build_eval_set(pool(), LABELS, SamplingConfig())
    assert by_source(result.items) == {"nvwa": 120, "openfda": 120, "rasff": 60}
    assert len({i.item_id for i in result.items}) == 300


def test_same_seed_same_items_whatever_the_input_order() -> None:
    first = build_eval_set(pool(), LABELS, SamplingConfig())
    second = build_eval_set(list(reversed(pool())), LABELS, SamplingConfig())
    assert first.items == second.items


def test_another_seed_gives_another_sample() -> None:
    first = build_eval_set(pool(), LABELS, SamplingConfig(seed=1))
    second = build_eval_set(pool(), LABELS, SamplingConfig(seed=2))
    assert {i.item_id for i in first.items} != {i.item_id for i in second.items}


def test_item_ids_are_short_and_derived_from_the_source_key() -> None:
    assert item_id("nvwa", "/actueel/nieuws/x") == item_id("nvwa", "/actueel/nieuws/x")
    assert item_id("openfda", "F-1").startswith("fd-")
    assert len(item_id("rasff", "2026.0001")) == len("ra-") + 8


def label_counts(items: list[EvalItem]) -> Counter[str | None]:
    return Counter(i.candidate.group for i in items)


def test_every_label_gets_its_floor_rare_ones_from_rasff() -> None:
    result = build_eval_set(pool(), LABELS, SamplingConfig())
    counts = label_counts(result.items)
    assert all(counts[label] >= 8 for label in LABELS)
    rasff = label_counts([i for i in result.items if i.source == "rasff"])
    assert rasff["TSEs"] >= 8 and rasff["radiation"] >= 8
    assert result.shortfall == {}


def test_labels_nobody_can_supply_are_reported_as_shortfall() -> None:
    few = [c for c in pool() if c.group != "TSEs"] + [cand("rasff", "2025.9999", "TSEs")]
    result = build_eval_set(few, LABELS, SamplingConfig())
    assert result.shortfall == {"TSEs": 7}
    assert by_source(result.items)["rasff"] == 60


def test_the_rest_of_a_quota_follows_group_sizes() -> None:
    skewed = [cand("nvwa", f"/a/{i}", "allergens") for i in range(300)]
    skewed += [cand("nvwa", f"/f/{i}", "foreign bodies") for i in range(100)]
    skewed += [c for c in pool() if c.source != "nvwa"]
    nvwa = [i for i in build_eval_set(skewed, LABELS, SamplingConfig()).items if i.source == "nvwa"]
    assert label_counts(nvwa) == {"allergens": 90, "foreign bodies": 30}


def test_floors_take_at_most_a_share_of_nvwa_and_fda_quotas() -> None:
    """Many rare FDA hazards must not crowd out FDA's common ones (pathogens here)."""
    rare = [f"rare {n}" for n in range(12)]
    fda = [cand("openfda", f"P-{i}", "pathogenic micro-organisms") for i in range(1000)]
    fda += [cand("openfda", f"R-{n}-{i}", label) for n, label in enumerate(rare) for i in range(10)]
    frame = fda + [c for c in pool() if c.source != "openfda"]
    result = build_eval_set(frame, (*LABELS, *rare), SamplingConfig())
    counts = label_counts([i for i in result.items if i.source == "openfda"])
    # proportional share 107 of 120, minus at most the floor budget (40% of 120 = 48)
    assert counts["pathogenic micro-organisms"] >= 107 - 48
    assert sum(result.shortfall.values()) > 0


def test_a_floor_prefers_the_source_where_the_label_is_relatively_common() -> None:
    """Radiation: 10 of 1,000 FDA candidates (1%) vs 10 of 200 RASFF ones (5%)."""
    frame = [cand("openfda", f"P-{i}", "pathogenic micro-organisms") for i in range(990)]
    frame += [cand("openfda", f"X-{i}", "radiation") for i in range(10)]
    frame += [cand("rasff", f"2025.{i:04}", "radiation" if i < 10 else "TSEs") for i in range(200)]
    frame += [c for c in pool() if c.source == "nvwa"]
    result = build_eval_set(frame, LABELS, SamplingConfig())
    radiation = Counter(i.source for i in result.items if i.candidate.group == "radiation")
    # proportional shares FDA 1 + RASFF 3; the four missing come from RASFF
    assert radiation == {"openfda": 1, "rasff": 7}


def test_dev_and_test_split_each_source_one_to_two() -> None:
    items = build_eval_set(pool(), LABELS, SamplingConfig()).items
    splits = Counter((i.source, i.split) for i in items)
    assert splits == {
        ("nvwa", "dev"): 40,
        ("nvwa", "test"): 80,
        ("openfda", "dev"): 40,
        ("openfda", "test"): 80,
        ("rasff", "dev"): 20,
        ("rasff", "test"): 40,
    }


def test_dev_has_the_same_strata_mix_as_test() -> None:
    items = build_eval_set(pool(), LABELS, SamplingConfig()).items
    nvwa = [i for i in items if i.source == "nvwa"]
    dev = Counter(i.stratum for i in nvwa if i.split == "dev")
    test = Counter(i.stratum for i in nvwa if i.split == "test")
    assert all(abs(2 * dev[s] - test[s]) <= 2 for s in test)


def test_rasff_items_are_the_noise_audit_and_60_items_form_the_agreement_subset() -> None:
    items = build_eval_set(pool(), LABELS, SamplingConfig()).items
    assert {i.source for i in items if i.noise_audit} == {"rasff"}
    assert sum(i.noise_audit for i in items) == 60
    assert Counter(i.source for i in items if i.agreement) == {
        "nvwa": 24,
        "openfda": 24,
        "rasff": 12,
    }


def test_dev_items_come_first_in_labelling_order() -> None:
    items = build_eval_set(pool(), LABELS, SamplingConfig()).items
    assert [i.split for i in items] == ["dev"] * 100 + ["test"] * 200


def test_one_item_per_fda_recall_event() -> None:
    clustered = [c for c in pool() if c.source != "openfda"]
    clustered += [
        cand("openfda", f"F-{i}", "allergens", cluster=f"E{i // 10}") for i in range(2000)
    ]
    items = build_eval_set(clustered, LABELS, SamplingConfig()).items
    events = [i.candidate.cluster for i in items if i.source == "openfda"]
    assert len(events) == 120
    assert len(set(events)) == 120


def test_an_excluded_item_is_replaced_from_its_stratum_and_keeps_split_and_flags() -> None:
    original = build_eval_set(pool(), LABELS, SamplingConfig()).items
    gone = next(i for i in original if i.source == "nvwa" and i.agreement and i.split == "dev")
    result = build_eval_set(pool(), LABELS, SamplingConfig(), exclusions=[gone.item_id])
    new = next(i for i in result.items if i.item_id not in {o.item_id for o in original})
    assert result.replacements[0].excluded == gone.item_id
    assert result.replacements[0].replaced_by == new.item_id
    assert (new.stratum, new.split, new.agreement) == (gone.stratum, "dev", True)
    assert {i.item_id for i in result.items} == (
        {o.item_id for o in original} - {gone.item_id} | {new.item_id}
    )


def test_replacing_twice_never_reuses_an_excluded_notification() -> None:
    original = build_eval_set(pool(), LABELS, SamplingConfig()).items
    first = next(i for i in original if i.source == "openfda")
    once = build_eval_set(pool(), LABELS, SamplingConfig(), exclusions=[first.item_id])
    second = once.replacements[0].replaced_by
    assert second is not None
    twice = build_eval_set(pool(), LABELS, SamplingConfig(), exclusions=[first.item_id, second])
    ids = {i.item_id for i in twice.items}
    assert first.item_id not in ids and second not in ids
    assert len(ids) == 300


def test_an_unknown_exclusion_is_reported_not_applied() -> None:
    result = build_eval_set(pool(), LABELS, SamplingConfig(), exclusions=["nv-00000000"])
    assert result.unknown_exclusions == ["nv-00000000"]
    assert len(result.items) == 300


def test_an_exhausted_stratum_borrows_from_the_same_source() -> None:
    tiny = [c for c in pool() if c.source != "nvwa"]
    tiny += [cand("nvwa", f"/fb/{i}", "foreign bodies") for i in range(118)]
    tiny += [cand("nvwa", f"/un/{i}", None) for i in range(5)]
    tiny += [cand("nvwa", f"/al/{i}", "allergens") for i in range(2)]
    items = build_eval_set(tiny, LABELS, SamplingConfig()).items
    allergens = [i for i in items if i.source == "nvwa" and i.candidate.group == "allergens"]
    assert len(allergens) == 2  # the whole stratum
    result = build_eval_set(tiny, LABELS, SamplingConfig(), exclusions=[allergens[0].item_id])
    new_id = result.replacements[0].replaced_by
    new = next(i for i in result.items if i.item_id == new_id)
    assert new.source == "nvwa"
    assert new.candidate.group != "allergens"
