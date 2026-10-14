# Eval set

The hand-labelled evaluation set of OpenFoodAlerts (spec §7), the RASFF silver set and the
local labelling page. **Data in this directory (`*.csv`, `sampling.json`) is licensed
CC BY 4.0**; the source texts inside it keep their Sources' terms (RASFF: CC BY 4.0, NVWA:
CC0 text, openFDA: US public domain). Code (`label_app.py`) is Apache-2.0 like the repo.

> Status (2026-10-25): sampled on the **draft** taxonomy (`db/seed/taxonomy/v1-draft.csv`)
> and on a local database without the full RASFF backfill. Re-run after ticket 11 (freeze)
> and ticket 08 (backfill), see [Re-running](#re-running). The tool works now; Labels made
> before the re-runs survive only for items that stay in the sample.

| File | What | Written by |
|---|---|---|
| `items.csv` | 300 eval items with their frozen model input | `ofa eval-sample` |
| `labels.csv` | Labels, one row per item and annotator pass | `label_app.py` (append only) |
| `exclusions.csv` | Items removed while labelling (non-food) and their replacements | `ofa eval-exclude` |
| `sampling.json` | Parameters and counts of the sample (frame sizes, allocation, shortfall) | `ofa eval-sample` |
| `silver.csv` | RASFF silver set | `ofa eval-silver` |
| `cache/`, `results/` | Model outputs and metrics | ticket 15 |

All CSVs: UTF-8 without BOM, LF, comma-separated, minimal quoting, header row, fixed column
order. Re-running a command on the same database gives byte-identical files (no
timestamps, seeded order).

## `items.csv`

| Column | Meaning |
|---|---|
| `item_id` | `nv-`/`fd-`/`ra-` + first 8 hex of sha256(`source_key`). Stable across re-runs |
| `split` | `dev` (100) or `test` (200). Test is only scored when explicitly asked for |
| `source` | `nvwa`, `openfda`, `rasff` |
| `source_key` | The Notification's key at its Source (NVWA URL path, FDA recall number, RASFF reference) |
| `source_url` | Official page (openFDA: API query URL) |
| `published_on` | Publication date (Europe/Amsterdam) |
| `stratum` | `<source>:<hazard group>`, the sampling stratum. A pre-label, **not** a Label |
| `noise_audit` | `true` for the 60 RASFF items: Labels are compared with the official categories |
| `agreement` | `true` for the 60 items the second annotator (B) labels (Cohen's κ) |
| `official_categories` | RASFF only: official Hazard categories, `; `-separated, source order |
| `input` | JSON object, the frozen model input (below). Keys in this order |

The file is in labelling order: dev items first, shuffled (seeded) within each split.

### Model input (`input`), per Source

Verbatim copies of the parsed Notification in the source language:

- **rasff**: `{"subject"}`. RASFF models see the subject only (spec §6.1), so T1 on RASFF
  measures what can be read from one line.
- **nvwa**: `{"title", "summary", "products"}`: page title, the `.intro` paragraph
  (`summary_source`) and the product lines (`product_text`; names, unmatched lines).
- **openfda**: `{"product_description", "reason_for_recall"}`. Firm name and city/state/
  country are left out: they locate the firm, not the product's origin (T4).

Classifiers (tickets 16-17) must build their prompt from these fields only; the T3 span must
be a verbatim substring of one field.

## `labels.csv`

| Column | Values |
|---|---|
| `item_id` | from `items.csv` |
| `annotator` | `A` (domain expert, all items) or `B` (second annotator, agreement subset) |
| `guideline_version` | version of `docs/annotation_guidelines.md` used, e.g. `v1` |
| `hazard_category` | T1: a label of the taxonomy CSV, or `unsure` |
| `product_category` | T2: a RASFF Product category name (`db/seed/rasff/product_categories.json`), or `unsure` |
| `hazard` | T3: Hazard copied verbatim from one input field, or `none` |
| `origin_country` | T4: ISO 3166-1 alpha-2, or `unknown` (only when the text states the origin) |
| `product_type` | T5: `food`, `feed`, `food contact material`, `non-food` |
| `note` | free text, optional |
| `labelled_at` | ISO 8601 UTC |

Rows are only appended. For one `(item_id, annotator, guideline_version)` the last row wins
(corrections). `unsure` means the annotator could not decide; the harness (ticket 15) is
expected to leave such items out of that task's metrics and report how many.

## Commands

From `pipeline/` (`uv run ofa …`), against `DATABASE_URL`:

```bash
uv run ofa eval-fetch-rasff --dry-run   # what RASFF the sample still needs (before ticket 08)
uv run ofa eval-fetch-rasff             # fetch it (rate limited, ≤150 requests by default)
uv run ofa parse --source rasff
uv run ofa eval-sample                  # items.csv, labels.csv header, sampling.json, eval_items
uv run ofa eval-silver                  # silver.csv + the excluded multi-category share
uv run ofa eval-exclude --from-labels   # replace items labelled non-food
uv run ofa eval-exclude nv-1a2b3c4d     # or name items explicitly (--reason …)
```

`eval-sample` refuses (exit code 3, nothing written) when the new sample would drop an item
that already has Labels; `--force` overrides. `--taxonomy PATH` picks another label set
(default `db/seed/taxonomy/v1.csv`, else `v1-draft.csv`); `--seed` defaults to 20261025.

## How the sample is drawn

Code: `pipeline/src/openfoodalerts/eval/` (`frame.py`, `sampling.py`, `keywords.py`).

1. **Frame** (Notifications published before 2026-10-25):
   NVWA from 2023-10-04 with rule Product type food (rule non-food and `pending` are out;
   withdrawals are out); openFDA from 2020 with Product type food or feed, one candidate per
   recall event; RASFF from 2020, food/feed/food contact material, no News, with at least
   one official Hazard.
2. **Hazard group** (stratum): RASFF uses the official category (the label shared by all
   Hazards, else the first Hazard's). NVWA and openFDA have none, so a transparent keyword
   rule set (`keywords.py`, English + Dutch, priority-ordered, first match wins; the recall
   reason or title + summary first, the whole input as fallback) guesses a RASFF category,
   which the taxonomy maps to a label. No match = `unmatched`. The same rules are the
   keyword baseline of ticket 15.
3. **Allocation**: NVWA 120, openFDA 120, RASFF 60. Each Source's quota is first spread over
   its groups in proportion to their frame sizes; then every T1 label is brought up to 8
   items where the frame allows, taking each extra item from the Source where the label is
   relatively most common and giving up an item of that Source's most over-sampled stratum.
   Floors may use at most 40% of the NVWA and openFDA quotas and all of RASFF's. Labels
   that still have fewer than 8 are listed under `shortfall` in `sampling.json`.
4. **Selection**: within a stratum, the lowest sha256(seed | source | source_key) ranks.
5. **Splits and flags**: per Source, items sorted by stratum and rank, every third one is
   dev (NVWA 40/80, FDA 40/80, RASFF 20/40). Agreement subset: 1 in 5 per Source with a
   second rank (24/24/12). All RASFF items are the noise audit set.
6. **Exclusions**: an item labelled non-food is replaced by the next ranked unused
   candidate of its stratum (else of its Source); the replacement inherits split and flags.
   `exclusions.csv` is replayed on every run.

`sampling.json` keeps `frame_sizes` and `allocation` per stratum, so metrics can be
reweighted to the frame (the label floors over-sample rare hazards on purpose).

## Silver set

`silver.csv` (`source_key, published_on, label, rasff_categories, subject`): RASFF
Notifications since 2020 whose official Hazards all map to one T1 label, stratified by label
(proportional, floor min(available, 25)), up to 2,000, eval items left out. `ofa
eval-silver` prints how many were excluded for spanning several labels (data card).

## Labelling

```bash
cd pipeline
uv run --group eval streamlit run ../eval/label_app.py
```

The `eval` dependency group (Streamlit) is not part of a plain `uv sync`. Pick annotator A
or B and the guideline version in the sidebar. One item at a time: the frozen input, a link
to the source page, the five tasks. "Save and next" validates (T3 must be copied verbatim
from one field) and appends to `labels.csv`. Close the tab whenever; the next start resumes
at the first item without your Label. Annotator B sees only the agreement subset and never
A's Labels. Commit `labels.csv` as you go.

## Re-running

After ticket 11 freezes `db/seed/taxonomy/v1.csv` (it becomes the default) and after the
full RASFF backfill (ticket 08):

```bash
uv run ofa parse --source rasff
uv run ofa eval-fetch-rasff --dry-run   # should plan nothing after the backfill
uv run ofa eval-sample                  # add --force if it refuses and you accept the change
uv run ofa eval-silver
```

Expect the RASFF 60 to change once the backfill fills the frame, and some NVWA/openFDA floor
items with them (the floors depend on what RASFF can supply); a changed label set changes
the strata too. Items that stay keep their ids and Labels. `eval-sample` lists labelled items
that would leave and stops; with `--force` their rows stay in `labels.csv` but are no longer
scored. So label sparingly (or only to try the tool and the guideline) until both re-runs
are done.
