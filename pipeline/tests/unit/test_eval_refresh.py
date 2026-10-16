"""`eval-refresh`: registered classifiers write the cache; none registered fails clearly."""

from collections.abc import Iterable, Sequence
from pathlib import Path

import pytest

from openfoodalerts.eval.cache import ModelOutput, read_cache
from openfoodalerts.eval.files import ItemRow
from openfoodalerts.eval.refresh import NoClassifierConfigured, refresh_cache


def item(item_id: str, split: str) -> ItemRow:
    return ItemRow(item_id, split, "nvwa", item_id, "", "", "", False, False, (), {"title": "x"})


def fake(items: Sequence[ItemRow]) -> Iterable[ModelOutput]:
    for i in items:
        yield ModelOutput(
            i.item_id, "hazard_category", "allergens", "high", False, None, "h", "fake", "v1",
            "1", "1", "2026-10-26T08:00:00+00:00",
        )  # fmt: skip


def test_without_a_classifier_refresh_fails_with_a_clear_message(tmp_path: Path) -> None:
    with pytest.raises(NoClassifierConfigured, match="no classifier configured"):
        refresh_cache([item("nv-1", "dev")], split="dev", cache_dir=tmp_path, classifiers={})


def test_refresh_sends_only_the_split_to_each_classifier_and_writes_the_cache(
    tmp_path: Path,
) -> None:
    items = [item("nv-1", "dev"), item("nv-2", "test")]
    written = refresh_cache(items, split="dev", cache_dir=tmp_path, classifiers={"fake": fake})
    assert written == {tmp_path / "fake" / "v1.jsonl": 1}
    [run] = read_cache(tmp_path)
    assert [p.item_id for p in run.outputs] == ["nv-1"]
    with pytest.raises(KeyError, match="nope"):
        refresh_cache(
            items, split="dev", cache_dir=tmp_path, classifiers={"fake": fake}, models=["nope"]
        )
