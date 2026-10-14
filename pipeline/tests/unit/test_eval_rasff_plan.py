"""Which RASFF Notifications to fetch so the eval set can fill its rare labels."""

from datetime import date
from pathlib import Path

from openfoodalerts.eval.labelset import load_taxonomy
from openfoodalerts.eval.rasff_fill import fetch_plan, rasff_demand
from openfoodalerts.eval.sampling import Candidate, SamplingConfig

TAXONOMY = (
    "rasff_id,name_en,notifications_since_2020-01-01,label\n"
    "21801,pathogenic micro-organisms,6000,pathogenic micro-organisms\n"
    "21798,allergens,500,allergens\n"
    "21789,TSEs,46,TSEs\n"
    "21791,radiation,53,radiation\n"
)


def cand(source: str, key: str, group: str | None) -> Candidate:
    return Candidate(source, key, 1, group, {"t": key}, date(2025, 1, 1), "https://x")


def frame() -> list[Candidate]:
    out = [cand("nvwa", f"/n/{i}", "allergens") for i in range(200)]
    out += [cand("openfda", f"F-{i}", "pathogenic micro-organisms") for i in range(200)]
    out += [cand("rasff", f"2026.{i:04}", "pathogenic micro-organisms") for i in range(100)]
    return out


def test_demand_follows_the_rasff_distribution_plus_the_floors(tmp_path: Path) -> None:
    path = tmp_path / "v1-draft.csv"
    path.write_text(TAXONOMY, encoding="utf-8")
    taxonomy = load_taxonomy(path)
    demand = rasff_demand(frame(), taxonomy, SamplingConfig())
    assert sum(demand.values()) == 60
    assert demand["TSEs"] == 8 and demand["radiation"] == 8
    assert demand["pathogenic micro-organisms"] > demand["allergens"]


def test_plan_fetches_what_the_local_frame_lacks_with_a_margin() -> None:
    demand = {"pathogenic micro-organisms": 40, "TSEs": 8, "radiation": 4}
    plan = fetch_plan(frame(), demand, margin=0.25, seed=1)
    # 100 local pathogen Notifications already cover 40 + 10
    assert plan == {"TSEs": 10, "radiation": 5}
