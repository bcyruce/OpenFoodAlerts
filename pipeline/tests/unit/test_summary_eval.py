"""T6 in `make eval-refresh` / `make eval`: the summaries of the eval items are cached next
to T1 (for the human fact-check), and the harness does not score them."""

from pathlib import Path

from openfoodalerts.eval.cache import read_cache
from openfoodalerts.eval.files import ItemRow
from openfoodalerts.eval.refresh import refresh_cache


def item(item_id: str, source: str, **snapshot: str) -> ItemRow:
    return ItemRow(item_id, "dev", source, item_id, "", "", "", False, False, (), snapshot)


ITEMS = [
    item("fd-1", "openfda", product_description="Brie 200g", reason_for_recall="Listeria."),
    item("nv-1", "nvwa", title="Waarschuwing Pindakaas", summary="Bevat glas.", products=""),
    item("ra-1", "rasff", subject="Aflatoxins in figs"),
]


def test_refresh_caches_a_summary_per_item_and_language_never_for_rasff(tmp_path: Path) -> None:
    refresh_cache(ITEMS, split="dev", cache_dir=tmp_path, models=["fake"])
    [run] = read_cache(tmp_path)
    summaries = {(o.task, o.item_id): o for o in run.outputs if o.task.startswith("summary_")}
    assert set(summaries) == {
        ("summary_en", "fd-1"),
        ("summary_nl", "fd-1"),
        ("summary_en", "nv-1"),
        ("summary_nl", "nv-1"),
        ("summary_zh", "nv-1"),
    }
    zh = summaries[("summary_zh", "nv-1")]
    assert (
        zh.value
        == "测试用假模型摘要：此处复述NVWA关于 Waarschuwing Pindakaas 的通报，不添加新的事实。"
    )
    assert (zh.abstained, zh.evidence_span, zh.taxonomy_version) == (False, None, "")
