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
| `cache/{model}/{prompt_version}.jsonl` | Cached model outputs, one line per item and task | `make eval-refresh` (ticket 16) |
| `results/latest.json` | Metrics of the latest `make eval` (both splits) | `make eval` |
| `results/example.json` | **Synthetic** example report for building `/evaluation` | `make eval-example` |

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
(corrections). For scoring, each item uses the annotator's row under the **highest guideline
version** that annotator used for it (`v10` > `v9`), so items relabelled under a new
guideline switch over one by one. `unsure` (and a blank value) means the annotator could not
decide: the harness leaves the item out of that task's metrics and reports it as `n_unsure`.

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

## Scoring: `make eval`

```bash
make eval                 # dev split (default); offline, no API key, no network
make eval SPLIT=test      # the test split, only when asked for (release tags)
make eval-refresh SPLIT=dev   # call the classifiers and refresh cache/ (paid API, ticket 16)
make eval-example         # regenerate the synthetic results/example.json
```

`make eval` (`ofa eval-run`) reads `items.csv`, `labels.csv`, every `cache/*/*.jsonl` and
`silver.csv`, scores each cached model and the two baselines on one split and writes
`results/latest.json`. Runs of the other split already in that file are kept, so dev and
test results live side by side. When `DATABASE_URL` answers it also inserts one `eval_runs`
row per (model or baseline, task, split) and rebuilds `eval_labels` from `labels.csv` (for
items in `eval_items`); without a database it prints a notice and still succeeds. With no
Labels yet, every run is listed under `skipped` and `runs` is empty: that is the state of
the committed `latest.json` until labelling starts.

Code: `pipeline/src/openfoodalerts/eval/` (`harness.py`, `metrics.py`, `labels.py`,
`cache.py`, `baselines.py`, `store.py`, `refresh.py`, `synthetic.py`).

### Model output cache

`cache/{model}/{prompt_version}.jsonl`, one JSON object per line and per (item, task),
sorted by (task, item_id), UTF-8, LF. Keys, in this order:

| Key | Value |
|---|---|
| `item_id` | from `items.csv` |
| `task` | `hazard_category`, `product_category`, `hazard`, `origin_country`, `product_type` |
| `value` | the output as text (T1 label, RASFF Product category, verbatim span, ISO2 or `unknown`, Product type); `null` when abstained |
| `confidence` | `high`, `medium`, `low`; `null` when abstained |
| `abstained` | `true` / `false` |
| `evidence_span` | substring of the input, or `null` |
| `input_hash` | `openfoodalerts.classify.input_hash.input_hash(input, prompt_version=…, model=…, taxonomy_version=…)` |
| `model`, `prompt_version` | must match the file's path |
| `schema_version`, `taxonomy_version` | as in `ai_classifications` |
| `created_at` | ISO 8601 |

`input_hash` = sha256 of the item's `input` as compact JSON (keys in order, strings NFC) +
`\n` + prompt_version + `\n` + model + `\n` + taxonomy_version. A cached line whose hash no
longer matches the item (the item's input changed, or the taxonomy did) is **stale**: it is
ignored and counted as an abstention (`n_stale`). An item without a cached line counts as
an abstention too (`n_missing`), so an incomplete cache cannot look better than a complete
one.

### Plugging in a classifier (ticket 16)

Register a function under its model name in `openfoodalerts.eval.refresh.CLASSIFIERS`. It
receives the `ItemRow`s of the split and yields one `ModelOutput` per item and task (it may
skip items whose cached `input_hash` is unchanged); `make eval-refresh` writes them with
`cache.write_outputs` (a new line replaces the cached one for the same item and task). Until
a classifier is registered, `make eval-refresh` exits 2 with "no classifier configured".

### Metrics

Which items count:

- Labels are annotator A's (see `labels.csv` above). Items without A's Label for a task, or
  with `unsure`, are left out of that task (`n_unlabelled`, `n_unsure`).
- T1 is scored on all three Sources (RASFF from the subject only); T2-T5 on NVWA and openFDA
  only (spec §6.1). Every task is reported per Source (`by_source`) and overall.
- Agreement and noise audit use all flagged items regardless of split (they compare Labels
  with Labels, not models).

Definitions (`metrics.py`, each checked against scikit-learn in the unit tests):

- **Abstention** = wrong. `accuracy` is over all scored items, abstentions included;
  `accuracy_answered` is over the answered ones; `abstention_rate` = abstained / n.
- **macro-F1 / weighted-F1** average over the labels present in the Labels or the outputs
  (scikit-learn's default label set), `abstain` excluded; a 0/0 precision or recall is 0, so
  a label that is output but never correct has F1 0. Weighted-F1 weights by Label support.
- **per_class**: precision, recall, F1, support per label (overall only).
- **confusion_matrix**: rows = Labels, columns = outputs; T1 labels in taxonomy order, T5 in
  Product type order, others sorted, `abstain` as the last row/column (its row is zero).
- **coverage_accuracy**: one point per confidence level: answer only when confidence ≥ the
  level (high; high+medium; all). `coverage` = answered / n, `accuracy` = correct /
  answered. Used to choose the "low confidence" threshold (ticket 21).
- **95% CIs** (`*_ci95`): percentile bootstrap over items, 1,000 resamples, seed 20261025
  (Python's `random`, so identical on every platform).
- **T3 hazard**: `exact_match` (identical strings) and `normalized_match` (NFKC, casefold,
  every Unicode punctuation character → space, whitespace collapsed: "E. coli O157:H7" =
  "e coli o157 h7"). A Label `none` (no Hazard named) is matched only by an abstention; an
  abstention matches nothing else.
- **T4 origin_country**: `exact_match`, and `normalized_match` after mapping both sides to
  ISO2 (case, the EU codes UK → GB, EL → GR, XI → GB, English RASFF country names). An
  abstention counts as `unknown`.
- **T5 product_type**: the classification metrics above (accuracy, confusion matrix, ...).
- **Agreement**: Cohen's κ between A and B on the agreement subset, per task (T1, T2, T4
  after ISO2, T5; pairs where either is `unsure` left out); the top-level value is T1's.
  `null` when undefined (no pairs, or both used a single category).
- **Noise audit**: on the RASFF items, the share where A's T1 Label is one of the T1 labels
  of the official RASFF categories (`official_categories` mapped through the taxonomy).
  `n_multi_label` counts items whose official categories map to more than one label;
  `n_unmapped` those with no mappable category.

Metrics are not reweighted to the frame: the label floors over-sample rare hazards
(`sampling.json` has what reweighting would need).

### Baselines (T1 only)

- `baseline-keywords` / `kw1`: the keyword rules of `keywords.py` (the same rules that made
  the NVWA / openFDA strata) mapped to T1 labels. Match in the hazard-bearing fields =
  confidence high, elsewhere in the input = medium, no match = abstain; the evidence span is
  the matched text. **Caveat:** the NVWA / openFDA eval sample is stratified by this rule's
  own output, which favours it.
- `baseline-tfidf-lr` / `silver1`: TF-IDF over character 2-5-grams + LogisticRegression
  (class-balanced, `random_state` 20261025) trained on `silver.csv` (RASFF subject → label)
  and applied to each item's whole input. Never abstains; confidence from the predicted
  probability (≥ 0.6 high, ≥ 0.3 medium). **Domain and language shift:** it learns from
  one-line, mostly English RASFF subjects and is tested on Dutch NVWA pages and long English
  openFDA recall texts, and the silver set has only 64 rows until the backfill. Skipped with
  a notice when the silver set has fewer than two labels.

Both are computed on the fly from the committed files (deterministic, ~seconds), not cached.

### `results/latest.json`

The spec §7.3 shape, extended only by added fields:

```jsonc
{
  "git_sha": "…", "created_at": "…",
  "taxonomy_version": 1,              // an integer once frozen; "v1-draft" until then
  "synthetic": false,                 // added: true only in example.json
  "bootstrap": {"resamples": 1000, "seed": 20261025, "level": 0.95},     // added
  "label_status": {"dev": {"items": 100, "labelled": 0}, "test": {…}},   // added
  "runs": [{
    "model": "…", "prompt_version": "…", "split": "dev", "task": "hazard_category",
    "kind": "model",                  // added: "model" or "baseline"
    "schema_version": "1", "taxonomy_version": 1,                         // added
    "by_source": {"nvwa": {…block…}, "openfda": {…}, "rasff": {…}},
    "overall": {…block…, "n_unsure": 0, "n_unlabelled": 0},
    "per_class": {"allergens": {"precision": 0.0, "recall": 0.0, "f1": 0.0, "support": 0}},
    "confusion_matrix": {"labels": ["…", "abstain"], "matrix": [[0]]}
  }],
  "skipped": [{"model": "…", "prompt_version": "…", "split": "dev", "task": "…",
               "reason": "no Labels"}],                                   // added
  "agreement": {"cohens_kappa": 0.0, "n": 60,
                "task": "hazard_category", "subset_size": 60, "by_task": {…}},  // added keys
  "noise_audit": {"agreement_with_official": 0.0, "n": 60,
                  "n_unsure": 0, "n_unmapped": 0, "n_multi_label": 0}    // added keys
}
```

A classification block (T1, T2, T5) has `n, accuracy, accuracy_ci95, accuracy_answered,
macro_f1, macro_f1_ci95, weighted_f1, abstention_rate, coverage_accuracy, n_missing,
n_stale`; a span block (T3, T4) has `n, exact_match, exact_match_ci95, normalized_match,
normalized_match_ci95, abstention_rate, n_missing, n_stale` and no per_class / confusion
matrix. Undefined values (n = 0) are `null`. `per_class` and `confusion_matrix` are overall
only.

`results/example.json` has the same shape with **invented** Labels and an invented
`synthetic-model` (`"synthetic": true`, `"git_sha": "synthetic"`); only the items and the
baselines' outputs are real. It exists so `/evaluation` (ticket 25) can be built now.

CI runs `make eval` on every PR with the committed files and does not compare the result
with the committed `latest.json` (`created_at` and `git_sha` always differ); the
regression gate is `eval.yml` (ticket 19).

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
