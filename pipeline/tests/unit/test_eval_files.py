from datetime import date
from pathlib import Path

from openfoodalerts.eval.files import (
    LABEL_COLUMNS,
    Exclusion,
    ensure_labels_file,
    read_exclusions,
    read_items,
    write_exclusions,
    write_items,
)
from openfoodalerts.eval.sampling import Candidate, EvalItem


def item(source: str, key: str, **flags: bool) -> EvalItem:
    snapshot = (
        {"subject": "Salmonella in chicken, from Poland"}
        if source == "rasff"
        else {
            "title": "Veiligheidswaarschuwing Gazpacho (melkallergie)",
            "summary": 'Eet "het" niet.\nZie etiket',
            "products": "",
        }
    )
    return EvalItem(
        item_id=f"{source[:2]}-0000000{len(key)}",
        candidate=Candidate(
            source=source,
            source_key=key,
            notification_id=7,
            group="allergens",
            snapshot=snapshot,
            published_on=date(2026, 10, 1),
            source_url="https://example.org/x",
            official_categories=("pathogenic micro-organisms", "allergens")
            if source == "rasff"
            else (),
        ),
        split="dev",
        noise_audit=flags.get("noise_audit", False),
        agreement=flags.get("agreement", False),
    )


def test_items_csv_has_a_fixed_header_and_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "items.csv"
    items = [item("nvwa", "/a", agreement=True), item("rasff", "2026.1", noise_audit=True)]
    write_items(path, items)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == (
        "item_id,split,source,source_key,source_url,published_on,stratum,noise_audit,"
        "agreement,official_categories,input"
    )
    rows = read_items(path)
    assert [r.item_id for r in rows] == [i.item_id for i in items]
    assert rows[0].input == items[0].candidate.snapshot
    assert list(rows[0].input) == ["title", "summary", "products"]
    assert (rows[0].agreement, rows[0].noise_audit) == (True, False)
    assert rows[1].official_categories == ("pathogenic micro-organisms", "allergens")
    assert rows[1].stratum == "rasff:allergens"
    assert rows[1].published_on == "2026-10-01"


def test_items_csv_is_utf8_without_bom_and_byte_identical_on_rewrite(tmp_path: Path) -> None:
    path = tmp_path / "items.csv"
    items = [item("nvwa", "/ü")]
    write_items(path, items)
    first = path.read_bytes()
    write_items(path, items)
    assert path.read_bytes() == first
    assert not first.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in first
    assert "melkallergie" in first.decode("utf-8")


def test_labels_file_is_created_with_its_header_only_once(tmp_path: Path) -> None:
    path = tmp_path / "labels.csv"
    ensure_labels_file(path)
    assert path.read_text(encoding="utf-8") == ",".join(LABEL_COLUMNS) + "\n"
    path.write_text(path.read_text(encoding="utf-8") + "x\n", encoding="utf-8")
    ensure_labels_file(path)
    assert path.read_text(encoding="utf-8").endswith("x\n")


def test_exclusions_round_trip_in_order(tmp_path: Path) -> None:
    path = tmp_path / "exclusions.csv"
    assert read_exclusions(path) == []
    rows = [Exclusion("nv-2", "non-food", "nv-9"), Exclusion("fd-1", "non-food", None)]
    write_exclusions(path, rows)
    assert read_exclusions(path) == rows
