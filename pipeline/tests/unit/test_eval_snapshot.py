from openfoodalerts.eval.snapshot import input_snapshot, snapshot_text

ROW = {
    "title": "Veiligheidswaarschuwing Gazpacho van Marqt (melkallergie)",
    "summary_source": "Ekoplaza waarschuwt voor Gazpacho van Marqt.",
    "product_text": "Gazpacho\nMarqt",
    "hazard_text": "should not be used",
    "source_fields": {"recalling_firm": "Firm Inc", "country": "United States"},
}


def test_rasff_gets_the_subject_only() -> None:
    assert input_snapshot("rasff", ROW | {"title": "Salmonella in chicken from Poland"}) == {
        "subject": "Salmonella in chicken from Poland"
    }


def test_nvwa_gets_title_summary_and_product_lines() -> None:
    assert input_snapshot("nvwa", ROW) == {
        "title": "Veiligheidswaarschuwing Gazpacho van Marqt (melkallergie)",
        "summary": "Ekoplaza waarschuwt voor Gazpacho van Marqt.",
        "products": "Gazpacho\nMarqt",
    }


def test_openfda_gets_description_and_reason_but_not_the_firm_location() -> None:
    row = ROW | {"product_text": "Tahini, 16 oz jar", "hazard_text": "Undeclared sesame"}
    assert input_snapshot("openfda", row) == {
        "product_description": "Tahini, 16 oz jar",
        "reason_for_recall": "Undeclared sesame",
    }


def test_missing_fields_become_empty_strings() -> None:
    assert input_snapshot("nvwa", {"title": "T"}) == {"title": "T", "summary": "", "products": ""}


def test_text_joins_the_fields_in_order() -> None:
    assert snapshot_text({"title": "A", "summary": "", "products": "B"}) == "A\nB"
