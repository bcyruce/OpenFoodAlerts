"""Which Label row counts: per item, the annotator's latest guideline version, last row wins."""

from openfoodalerts.eval.labels import label_value, latest_labels


def _row(item: str, annotator: str, version: str, t1: str) -> dict[str, str]:
    return {
        "item_id": item,
        "annotator": annotator,
        "guideline_version": version,
        "hazard_category": t1,
        "product_category": "unsure",
        "hazard": "none",
        "origin_country": "unknown",
        "product_type": "food",
        "note": "",
        "labelled_at": "2026-10-26T08:00:00+00:00",
    }


def test_last_row_of_the_latest_guideline_version_wins_per_annotator() -> None:
    rows = [
        _row("nv-1", "A", "v2", "allergens"),
        _row("nv-1", "A", "v1", "labelling"),  # older guideline, appended later
        _row("nv-1", "A", "v2", "foreign bodies"),  # correction under v2
        _row("nv-1", "B", "v2", "mycotoxins"),
        _row("nv-2", "A", "v9", "other"),
        _row("nv-2", "A", "v10", "allergens"),  # v10 is newer than v9
    ]
    a = latest_labels(rows, "A")
    assert a["nv-1"]["hazard_category"] == "foreign bodies"
    assert a["nv-2"]["hazard_category"] == "allergens"
    assert latest_labels(rows, "B")["nv-1"]["hazard_category"] == "mycotoxins"
    assert latest_labels([], "A") == {}


def test_gold_value_leaves_out_unsure_and_blank() -> None:
    row = _row("nv-1", "A", "v1", "allergens") | {"product_category": "unsure", "hazard": ""}
    assert label_value(row, "hazard_category") == "allergens"
    assert label_value(row, "product_category") is None
    assert label_value(row, "hazard") is None
    # "none" (no Hazard named) and "unknown" (origin not stated) are real Labels
    assert label_value(row | {"hazard": "none"}, "hazard") == "none"
    assert label_value(row, "origin_country") == "unknown"
    assert label_value(None, "hazard_category") is None
