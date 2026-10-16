"""Metric definitions of the eval harness, checked against scikit-learn on small samples."""

import pytest
from sklearn.metrics import (
    accuracy_score,
    cohen_kappa_score,
    confusion_matrix,
    f1_score,
    precision_recall_fscore_support,
)

from openfoodalerts.eval import metrics
from openfoodalerts.eval.metrics import ABSTAIN

GOLD = ["allergens", "allergens", "pathogens", "pathogens", "pathogens", "foreign", "other"]
PRED = ["allergens", "pathogens", "pathogens", ABSTAIN, "pathogens", "allergens", "mycotoxins"]


def test_accuracy_counts_an_abstention_as_wrong() -> None:
    assert metrics.accuracy(GOLD, PRED) == pytest.approx(accuracy_score(GOLD, PRED))
    assert metrics.accuracy(GOLD, PRED) == pytest.approx(3 / 7)


def test_macro_f1_averages_over_gold_and_predicted_labels_but_not_abstain() -> None:
    labels = sorted((set(GOLD) | set(PRED)) - {ABSTAIN})
    expected = f1_score(GOLD, PRED, labels=labels, average="macro", zero_division=0)
    assert metrics.macro_f1(GOLD, PRED) == pytest.approx(expected)


def test_weighted_f1_weights_by_gold_support() -> None:
    labels = sorted((set(GOLD) | set(PRED)) - {ABSTAIN})
    expected = f1_score(GOLD, PRED, labels=labels, average="weighted", zero_division=0)
    assert metrics.weighted_f1(GOLD, PRED) == pytest.approx(expected)


def test_per_class_matches_precision_recall_fscore_support() -> None:
    labels = sorted((set(GOLD) | set(PRED)) - {ABSTAIN})
    p, r, f, s = precision_recall_fscore_support(GOLD, PRED, labels=labels, zero_division=0)
    per_class = metrics.per_class(GOLD, PRED)
    assert list(per_class) == labels
    for i, label in enumerate(labels):
        assert per_class[label]["precision"] == pytest.approx(p[i])
        assert per_class[label]["recall"] == pytest.approx(r[i])
        assert per_class[label]["f1"] == pytest.approx(f[i])
        assert per_class[label]["support"] == s[i]


def test_confusion_matrix_has_gold_rows_and_an_abstain_column() -> None:
    cm = metrics.confusion(GOLD, PRED, order=["pathogens", "allergens"])
    # the given order first, remaining labels sorted, abstain last
    assert cm["labels"] == ["pathogens", "allergens", "foreign", "mycotoxins", "other", ABSTAIN]
    assert cm["matrix"] == confusion_matrix(GOLD, PRED, labels=cm["labels"]).tolist()
    assert cm["matrix"][0] == [2, 0, 0, 0, 0, 1]


def test_empty_samples_give_none_not_zero() -> None:
    assert metrics.accuracy([], []) is None
    assert metrics.macro_f1([], []) is None
    assert metrics.weighted_f1([], []) is None
    assert metrics.abstention_rate([]) is None
    assert metrics.bootstrap_ci([], [], metrics.accuracy, seed=1) is None
    assert metrics.confusion([], []) == {"labels": [ABSTAIN], "matrix": [[0]]}


def test_abstention_rate() -> None:
    assert metrics.abstention_rate(PRED) == pytest.approx(1 / 7)


def test_coverage_accuracy_curve_admits_one_more_confidence_level_per_point() -> None:
    gold = ["a", "a", "b", "b", "c"]
    pred = ["a", "b", "b", "a", ABSTAIN]
    confidence = ["high", "medium", "high", "low", None]
    curve = metrics.coverage_accuracy(gold, pred, confidence)
    assert curve == [
        {"min_confidence": "high", "coverage": pytest.approx(2 / 5), "accuracy": 1.0, "n": 2},
        {"min_confidence": "medium", "coverage": pytest.approx(3 / 5), "accuracy": 2 / 3, "n": 3},
        {"min_confidence": "low", "coverage": pytest.approx(4 / 5), "accuracy": 0.5, "n": 4},
    ]
    # nothing covered at a level: accuracy is undefined
    assert metrics.coverage_accuracy(["a"], [ABSTAIN], [None])[0]["accuracy"] is None


def test_bootstrap_ci_is_reproducible_for_a_seed_and_brackets_the_estimate() -> None:
    gold = GOLD * 6
    pred = PRED * 6
    ci = metrics.bootstrap_ci(gold, pred, metrics.macro_f1, seed=20261025)
    assert ci == metrics.bootstrap_ci(gold, pred, metrics.macro_f1, seed=20261025)
    assert ci != metrics.bootstrap_ci(gold, pred, metrics.macro_f1, seed=7)
    assert ci is not None
    estimate = metrics.macro_f1(gold, pred)
    assert estimate is not None
    assert ci[0] < estimate < ci[1]
    # no variation to resample: a degenerate interval
    assert metrics.bootstrap_ci(["a"] * 5, ["a"] * 5, metrics.accuracy, seed=1) == [1.0, 1.0]


def test_cohens_kappa_matches_scikit_learn() -> None:
    a = ["x", "x", "y", "y", "z", "x", "y", "z", "z", "x"]
    b = ["x", "y", "y", "y", "z", "x", "x", "z", "y", "x"]
    assert metrics.cohens_kappa(a, b) == pytest.approx(cohen_kappa_score(a, b))
    assert metrics.cohens_kappa(a, a) == pytest.approx(1.0)


def test_cohens_kappa_is_undefined_without_data_or_variation() -> None:
    assert metrics.cohens_kappa([], []) is None
    # both annotators used one and the same category: chance agreement is 1
    assert metrics.cohens_kappa(["x", "x"], ["x", "x"]) is None


@pytest.mark.parametrize(
    ("text", "normalized"),
    [
        ("  Undeclared   MILK. ", "undeclared milk"),
        ("E. coli O157:H7", "e coli o157 h7"),
        ("cross-contact with peanuts", "cross contact with peanuts"),
        ("\ufb01bres", "fibres"),  # NFKC: the fi ligature
        ("Salmonella\u00a0spp.", "salmonella spp"),  # no-break space
    ],
)
def test_span_normalization(text: str, normalized: str) -> None:
    assert metrics.normalize_span(text) == normalized


def test_span_match_exact_and_normalized() -> None:
    assert metrics.span_match("Listeria monocytogenes", "Listeria monocytogenes") == (True, True)
    assert metrics.span_match("listeria monocytogenes.", "Listeria monocytogenes") == (
        False,
        True,
    )
    assert metrics.span_match("Listeria", "Listeria monocytogenes") == (False, False)
    # a Label "none" (no Hazard in the text) is matched by an abstention only
    assert metrics.span_match(ABSTAIN, "none") == (True, True)
    assert metrics.span_match("milk", "none") == (False, False)
    assert metrics.span_match(ABSTAIN, "milk") == (False, False)


@pytest.mark.parametrize(
    ("value", "iso2"),
    [
        ("NL", "NL"),
        (" nl ", "NL"),
        ("UK", "GB"),
        ("EL", "GR"),
        ("XI", "GB"),
        ("Netherlands", "NL"),
        ("united states", "US"),
        ("unknown", "unknown"),
        ("", "unknown"),
        (ABSTAIN, "unknown"),
    ],
)
def test_country_normalization_to_iso2(value: str, iso2: str) -> None:
    assert metrics.to_iso2(value) == iso2
