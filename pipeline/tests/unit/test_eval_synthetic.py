"""The synthetic example report (eval/results/example.json) for building /evaluation."""

from openfoodalerts.eval.files import read_items
from openfoodalerts.eval.job import default_eval_dir
from openfoodalerts.eval.labelset import default_taxonomy_path, load_taxonomy
from openfoodalerts.eval.synthetic import SYNTHETIC_MODEL, example_report


def test_the_example_covers_every_part_of_the_report_and_is_reproducible() -> None:
    items = read_items(default_eval_dir() / "items.csv")
    taxonomy = load_taxonomy(default_taxonomy_path())
    silver = default_eval_dir() / "silver.csv"
    report = example_report(items, taxonomy, silver)
    assert report["synthetic"] is True
    assert report["git_sha"] == "synthetic"
    keys = {(r["model"], r["split"], r["task"]) for r in report["runs"]}
    for split in ("dev", "test"):
        for task in (
            "hazard_category",
            "product_category",
            "hazard",
            "origin_country",
            "product_type",
        ):
            assert (SYNTHETIC_MODEL, split, task) in keys
        assert ("baseline-keywords", split, "hazard_category") in keys
        assert ("baseline-tfidf-lr", split, "hazard_category") in keys
    assert report["agreement"]["n"] > 0
    assert report["agreement"]["cohens_kappa"] is not None
    assert report["noise_audit"]["n"] > 0
    t1 = next(
        r
        for r in report["runs"]
        if (r["model"], r["split"], r["task"]) == (SYNTHETIC_MODEL, "dev", "hazard_category")
    )
    assert 0.5 < t1["overall"]["macro_f1"] < 0.95
    assert set(t1["by_source"]) == {"nvwa", "openfda", "rasff"}
    assert example_report(items, taxonomy, silver) == report
