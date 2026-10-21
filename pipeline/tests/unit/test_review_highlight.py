"""The evidence span highlighted in the text shown on the review page."""

from openfoodalerts.classify.review_queue import highlight


def test_the_span_is_marked_in_the_text() -> None:
    assert highlight("Recall: undeclared milk in cookies", "undeclared milk") == (
        "Recall: <mark>undeclared milk</mark> in cookies"
    )


def test_whitespace_is_matched_as_the_evidence_check_does() -> None:
    assert highlight("Undeclared\n  milk", "Undeclared milk") == "<mark>Undeclared milk</mark>"


def test_text_is_escaped() -> None:
    assert highlight("<b>Milk</b> & eggs", "& eggs") == (
        "&lt;b&gt;Milk&lt;/b&gt; <mark>&amp; eggs</mark>"
    )


def test_without_a_span_in_the_text_nothing_is_marked() -> None:
    assert highlight("Undeclared milk", None) == "Undeclared milk"
    assert highlight("Undeclared milk", "eggs") == "Undeclared milk"
    assert highlight("", "eggs") == ""


def test_every_occurrence_is_marked() -> None:
    assert highlight("milk, milk", "milk") == "<mark>milk</mark>, <mark>milk</mark>"
