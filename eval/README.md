# Eval set

The hand-labelled evaluation set of OpenFoodAlerts (spec §7), the RASFF silver set and the
local labelling page. **Data in this directory (`*.csv`, `sampling.json`) is licensed
CC BY 4.0**; the source texts inside it keep their Sources' terms (RASFF: CC BY 4.0, NVWA:
CC0 text, openFDA: US public domain). Code (`label_app.py`, `factcheck_app.py`, `review_app.py`) is Apache-2.0 like the repo.

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
| `results/badge.json` | shields.io endpoint for the README badge (T1 macro-F1, test) | `make eval` / `ofa eval-badge` |
| `factcheck/t6.csv` | Sampled T6 summaries and the owner's factual-consistency judgments | `make factcheck-sample` + `factcheck_app.py` |

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

## Reviewing production AI classifications (not eval data)

```bash
cd pipeline
uv run ofa review-stats                                   # queue size per task
uv run --group eval streamlit run ../eval/review_app.py   # the review page (DATABASE_URL)
```

`review_app.py` lives here because it shares the Streamlit dependency group; it works on the
`review_queue` view of the database, not on these files (spec §6.5, ticket 20).

## Scoring: `make eval`

```bash
make eval                 # dev split (default); offline, no API key, no network
make eval SPLIT=test      # the test split, only when asked for (release tags)
make eval-refresh SPLIT=dev   # call MODEL (default claude-haiku-5-5) and refresh cache/ (paid API)
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
| `task` | `hazard_category`, `product_category`, `hazard`, `origin_country`, `product_type`; T6 `summary_en`, `summary_nl`, `summary_zh` (not scored, see [T6 fact-check](#t6-summaries-the-human-fact-check)) |
| `value` | the output as text (T1 label, RASFF Product category, verbatim span, ISO2 or `unknown`, Product type, summary); `null` when abstained |
| `confidence` | `high`, `medium`, `low`; `null` when abstained |
| `abstained` | `true` / `false` |
| `evidence_span` | substring of the input, or `null` |
| `input_hash` | `openfoodalerts.classify.input_hash.input_hash(input, prompt_version=…, model=…, taxonomy_version=…)` |
| `model`, `prompt_version` | must match the file's path |
| `schema_version`, `taxonomy_version` | as in `ai_classifications` |
| `created_at` | ISO 8601 |

`input_hash` = sha256 of the item's `input` as compact JSON (keys in order, strings NFC) +
`\n` + prompt_version + `\n` + model + `\n` + taxonomy_version (T1's taxonomy version; empty
for T2-T5, which have no taxonomy: their fixed lists are part of the prompt version). A
cached line whose hash no
longer matches the item (the item's input changed, or the taxonomy did) is **stale**: it is
ignored and counted as an abstention (`n_stale`). An item without a cached line counts as
an abstention too (`n_missing`), so an incomplete cache cannot look better than a complete
one.

### Refreshing the cache: `make eval-refresh` (ticket 16)

```bash
export ANTHROPIC_API_KEY=...            # or put it in .env
make eval-refresh SPLIT=dev             # MODEL=claude-haiku-5-5 (default): paid API
export DEEPSEEK_API_KEY=...
make eval-refresh SPLIT=dev MODEL=deepseek-flash   # the second candidate (spec §6.4): paid API
make eval-refresh SPLIT=dev MODEL=fake  # keyword rules in the model's place: no API, no cost
```

Each refresh also writes `cache/{model}/usage.json` (ticket 21): per split and task, the
prompt version, the summed token usage (`requests`, `input_tokens` (uncached),
`output_tokens` (incl. thinking / reasoning), `cache_creation_input_tokens`,
`cache_read_input_tokens`; OpenAI's and DeepSeek's usage is normalised to this meaning) and
`refreshed_at`. `make eval` does not read it; `ofa eval-compare` (the cost side of the model
choice) and `ofa classify --batch --dry-run` (the backfill estimate) do. Commit it with the
cache file.

`ofa eval-refresh --model M` runs model M on the split's items with the newest prompt of
each task (`prompts/{task}/vN.md`: T1 hazard_category, T2 product_category, T3 hazard, T4
origin_country, T5 product_type; ticket 17) and writes `cache/M/vN.jsonl`. It uses the
same code as `ofa classify` (`openfoodalerts.classify`): the item's frozen `input` is the
model input, the output is validated in code (an `evidence_span` that is not in the input
is an abstention), and `input_hash` is the one `ai_classifications` stores. T1 runs on all
three Sources (RASFF: subject only), T2-T5 on NVWA and openFDA (T5 on every NVWA / openFDA
item, although in production it only runs where the Product type rules cannot decide).
The cache file is per prompt version: all five tasks are v1 now; when one task moves to
v2 alone its lines go to `v2.jsonl` and are scored as their own run. T6 (ticket 18) writes one summary per item and
language (NVWA en/nl/zh, openFDA en/nl, never RASFF) into the same file, `taxonomy_version`
"", `evidence_span` null. Identical inputs are sent once per task; every refresh calls
the model again for every item (re-run only when the prompt, the model or the items
change). Token usage is printed as an `eval_refresh_usage` JSON line on stderr. Without
the model's key (`ANTHROPIC_API_KEY` for Claude, `DEEPSEEK_API_KEY` for DeepSeek Flash,
`OPENAI_API_KEY` for GPT-5 mini) it exits
2 before any call.

`fake` exists to exercise the whole path offline (tests, demos). Its cache, `cache/fake/`,
is git-ignored and must not be committed; `make eval` scores it like any model, so remove
`cache/fake/` (or restore `results/latest.json`) before committing results.

Registration: `openfoodalerts.eval.refresh.CLASSIFIERS` maps a model name to a function
that receives the split's `ItemRow`s and yields one `ModelOutput` per item and task; the
models come from `openfoodalerts.classify.registry` via `classify/eval_adapter.py`.
`make eval-refresh` writes them with `cache.write_outputs` (a new line replaces the cached
one for the same item and task).

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

Added by ticket 18, always present: `"t6_factcheck"` (the human fact-check of T6 summaries,
all splits, see below):

```jsonc
"t6_factcheck": {
  "file": "eval/factcheck/t6.csv", "sample_size": 50,
  "runs": [{                           // one per (model, prompt_version, split) in t6.csv
    "model": "claude-haiku-5-5", "prompt_version": "v1", "split": "dev",
    "n_sampled": 50,                   // rows whose text is still current (stale ones left out)
    "n_checked": 50, "n_consistent": 47,
    "consistency_rate": 0.94,          // n_consistent / n_checked; null when nothing checked
    "consistency_rate_ci95": [0.86, 1.0],  // percentile bootstrap, same settings as above
    "n_stale": 0,                      // judged texts that are no longer current (see below)
    "by_locale": {"en": {"n_checked": 20, "n_consistent": 19}, "nl": {…}, "zh": {…}},
    "by_source": {"nvwa": {…}, "openfda": {…}},
    "failures": [{"item_id": "…", "source": "nvwa", "locale": "zh",   // at most 10
                  "summary": "…", "problem": "the owner's note"}]
  }]
}
```

`runs` is `[]` until a sample exists.

Optional, read by `/en/evaluation` when present (ticket 21 adds it): `"thresholds": [{"model",
"prompt_version", "task", "min_confidence": "high" | "medium" | "low"}]`, the low-confidence
threshold chosen on the dev coverage–accuracy curve; the page marks it on that run's curves.
Written by `ofa eval-threshold` (below), which adds the fields `split` ("dev"), `rule`,
`target_accuracy`, `met_target`, `coverage`, `accuracy`, `n` (the chosen point); the page
reads only the four above.

Optional, written by `ofa eval-compare` (below), not shown by the page yet: `"model_selection"`:

```jsonc
"model_selection": {
  "rule": "spec §6.4: default claude-haiku-5-5; if deepseek-flash's dev hazard_category macro-F1 is at least claude-haiku-5-5's minus 2 points, the cheaper of the two",
  "split": "dev", "task": "hazard_category", "metric": "overall.macro_f1", "max_gap": 0.02,
  "default_model": "claude-haiku-5-5", "challenger": "deepseek-flash",
  "status": "compared",                // or "pending": a dev score (n > 0) is missing for either model
  "selected": "claude-haiku-5-5",      // the default while pending
  "gap": 0.013,                        // default − challenger macro-F1 (null while pending)
  "within_gap": true,                  // gap <= max_gap (exactly 2 points counts as within)
  "cheaper": "claude-haiku-5-5",       // lower cost_per_1000_requests_usd
  "reason": "…", "notices": ["…"],     // e.g. a nominal cost basis, a model's shutdown date,
                                       // the off-peak cost of a model compared at its peak price
  "candidates": [{"model": "…", "prompt_version": "v1", "macro_f1": 0.0, "macro_f1_ci95": [0.0, 0.0],
                  "n": 100, "cost_basis": "measured" | "nominal",
                  "tokens_per_request": {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0},
                  "cost_per_1000_requests_usd": 0.0,          // standard price (DeepSeek: peak)
                  "cost_per_1000_requests_off_peak_usd": 0.0}], // DeepSeek only
  "prices": {"file": "eval/model_prices.json", "verified_on": "2026-10-25"},
  "decided_at": "…", "git_sha": "…"
}
```

`make eval` keeps both blocks (`thresholds`, `model_selection`) from the previous
latest.json: they are decisions, re-made only by their commands.

### T6 summaries: the human fact-check

Spec §7.2: T6 is evaluated by a factual-consistency check of 50 summaries by the owner, not
by ROUGE. Steps (offline after the refresh):

```bash
make eval-refresh SPLIT=dev                  # caches T6 summaries next to T1 (paid API)
make factcheck-sample SPLIT=dev              # 50 summaries -> factcheck/t6.csv (MODEL=…)
make factcheck-app                           # judge them (Streamlit), or edit the CSV
make eval                                    # latest.json "t6_factcheck"; commit t6.csv
```

- **Sample** (`openfoodalerts.eval.factcheck.sample_factcheck`): the non-abstained summaries
  of one model and prompt version on one split whose `input_hash` matches the item's
  frozen input; split into the five strata NVWA en / nl / zh and openFDA en / nl and taken
  round-robin (10 each when every stratum has 10), each stratum in a fixed order
  (sha256 of seed 20261025, item and task). Same cache → same sample. Sampling again keeps
  every judgment whose summary text is unchanged, keeps judged rows that fell out of the
  sample, and drops unjudged ones.
- **Judgment**: `consistent` = `yes` when every statement of the summary is supported by
  the source text and nothing is added (no new facts, numbers, advice or severity
  judgement); `no` with a `problem` note otherwise; empty = not checked. Abstained
  summaries are not sampled (they are shown as source text, not as AI text).
- **`factcheck/t6.csv`** columns: `item_id, split, source, task, locale, model,
  prompt_version, input_hash, input` (the frozen input as JSON) `, summary, consistent,
  problem, checker, checked_at`. The CSV carries the judged text, so it stays meaningful
  without the cache (fake-model caches are not committed).
- **Stale**: a judged row whose item input has changed since (the hash no longer matches
  items.csv), or whose summary differs from the cached one for that model, prompt version,
  item and task (a refresh produced a new text). Stale rows are reported as `n_stale` and
  left out of the counts; re-sample and judge again.

### `results/badge.json`

Written by `ofa eval-run` next to the report it writes (`ofa eval-badge [--report PATH]`
rebuilds it from an existing report; it refuses a synthetic one, exit code 2). The
[shields.io endpoint schema](https://shields.io/badges/endpoint-badge):
`{"schemaVersion": 1, "label": "T1 macro-F1 (test)", "message": …, "color": …}`. Message:
"no labels yet" (no Labels in any split); "no test run yet" (no model run on test, baselines
do not count); one model: `"<model> 0.71 (95% CI 0.63–0.79)"`; several: every model with its
value, none picked (`"a 0.71 · b 0.69"`). The colour is a neutral blue (lightgrey without a
number), not a verdict. Commit it together with `latest.json`.

`results/example.json` has the same shape with **invented** Labels and an invented
`synthetic-model` (`"synthetic": true`, `"git_sha": "synthetic"`); only the items and the
baselines' outputs are real. It exists so `/evaluation` (ticket 25) can be built now.

CI runs `make eval` on every PR with the committed files and does not compare the result
with the committed `latest.json` (`created_at` and `git_sha` always differ); the
regression gate is `eval.yml` (ticket 19), below.

## Decisions on dev: model and threshold (ticket 21)

Both commands are offline (they read `results/latest.json`, write it back and print what
they decided), refuse `--split test` and synthetic reports (exit code 2), and do nothing
harmful without Labels: the model comparison is recorded as `pending` (the default model
stands) and no threshold is chosen (the file is left unchanged).

```bash
make eval-refresh SPLIT=dev                     # Claude Haiku 5.5 (ANTHROPIC_API_KEY)
make eval-refresh SPLIT=dev MODEL=deepseek-flash   # DeepSeek Flash (DEEPSEEK_API_KEY)
make eval                                       # scores both on dev
make eval-compare                               # ofa eval-compare -> model_selection
make eval-threshold                             # ofa eval-threshold -> thresholds + review_settings
```

**Model** (`ofa eval-compare`, spec §6.4, `openfoodalerts.eval.selection.select_model`): on
dev, T1 hazard_category, overall macro-F1 of each candidate's newest prompt version. The
default is `claude-haiku-5-5`; if `deepseek-flash` (which replaced GPT-5 mini as the
challenger) scores at least Haiku's macro-F1 minus 2 points (a gap of exactly 2 points
counts as within, as in the CI gate), the cheaper one is selected. Cheaper = lower cost per
request at **standard** prices from [`model_prices.json`](model_prices.json) (verified on
the official price pages, sources and date in the file and spec §16 V1; for DeepSeek the
**peak** price, because our timers do not keep to its off-peak hours; the off-peak cost is
reported beside it with a notice) times the tokens per request that `make eval-refresh`
measured on dev for all tasks (`cache/{model}/usage.json`); when either model has no
measured usage, a nominal request (200 input, 4,000 cached input, 300 output tokens) is
used and a notice says so. Point estimates only (dev has ~100 items; the CIs are reported
in `candidates`). A challenger that is more than 2 points better but dearer is not chosen
by the rule; a notice flags it for the owner. A selected model with an announced shutdown
(GPT-5 mini: 2026-12-11) gets a notice. `ofa classify` does **not** read the selection: pass
`--model` to use a model other than the default. DeepSeek has no Batch API: if it is
selected, the backfill is `ofa classify --task all --model deepseek-flash --concurrency N`
(synchronous, interruptible like any run), not `--batch`.

**Threshold** (`ofa eval-threshold`, spec §6.3, `choose_threshold`): per task with a
coverage–accuracy curve (T1, T2, T5; T3/T4 blocks have none and keep the default), on dev,
for the selected model (`model_selection.selected`, else Haiku; `--model` overrides) and
its newest prompt version: the confidence level with the **widest coverage whose accuracy
(correct / answered) is at least `--target-accuracy`** (default 0.90; `make eval-threshold
TARGET_ACCURACY=…`), counting only levels with at least `--min-n` answered items (default
1). If no level reaches the target, `high` (only high-confidence answers are accepted
without review). The result goes into latest.json `thresholds` (replacing the entry for the
same model, prompt version and task) and, unless `--no-db`, into the review queue's
`review_settings` (as `ofa review-threshold`; a database that does not answer is a notice).
The threshold only decides what is queued for human review (abstains always are); AI fields
are shown at once regardless (spec §6.5).

## Batch backfill: `ofa classify --batch` (ticket 21)

Not eval data, but it uses the files above: the backfill of all historical NVWA / openFDA
Notifications through the providers' Batch APIs (half price). From `pipeline/`:

```bash
uv run ofa classify --batch --task all --dry-run   # requests, batches, MB, estimated cost
uv run ofa classify --batch --task product_type    # T5 first (it decides the others' scope)
uv run ofa classify-batch-status --wait            # poll and store (Ctrl+C is safe)
uv run ofa classify --batch --task all             # then everything else; re-run to resume
```

The estimate multiplies the requests by the tokens per request measured on dev for that
task (`cache/{model}/usage.json`, else the nominal request) and the Batch prices of
`model_prices.json`. State is in the private tables `classify_batches` /
`classify_batch_requests` (migration `20261025001700`); see
`openfoodalerts/classify/batch.py` for submission, resume and failure handling.

## CI gate (`eval.yml`, ticket 19)

`.github/workflows/eval.yml` has two jobs.

**Pull requests** that change `prompts/**`, `eval/**`, `db/seed/taxonomy/**`,
`pipeline/src/openfoodalerts/classify/**`, `pipeline/src/openfoodalerts/eval/**` or the
workflow itself: `make eval-refresh SPLIT=dev` (paid API, about 100 requests) → `make eval`
(no database in that job: the `eval_runs` rows are skipped with a notice) → `ofa eval-gate`
against `eval/results/latest.json` as committed on the PR's base branch (main). The
comparison table goes to the job summary; `results/latest.json`, `results/badge.json` and
`cache/` are uploaded as the artifact `eval-dev-pr<N>` (30 days). The workflow never
commits: to publish the refreshed numbers, unzip the artifact into `eval/` and commit it on
the PR (that push re-runs the gate, which then compares the same prompt again).

```bash
uv run ofa eval-gate --base main-latest.json --head ../eval/results/latest.json \
  --task hazard_category --split dev --max-drop 0.02 [--summary "$GITHUB_STEP_SUMMARY"]
```

The rule (`openfoodalerts/eval/gate.py`):

- Only **model** runs of the task and split are gated; baselines are in the table for
  information. Per model, each side takes its run with the **newest prompt version**
  (`v10` > `v9`): a PR that adds `v2` still has main's `v1` cache, which `make eval` scores
  too, so the gate compares the PR's `v2` with main's newest.
- A model present on both sides with a number on both sides **fails** when
  main − PR > 0.02 (overall macro-F1, 2 percentage points; exactly 2 passes). Point
  estimates only: the bootstrap intervals are shown, not used (on 100 dev items they are
  about ±0.1 wide, so an interval rule would never fire).
- **Passes with a notice**: main has no `latest.json`; no Labels on the split (today's
  state: every run is skipped); a run with n = 0 (macro-F1 `null`); a model only on one
  side (new, or no longer cached).
- Exit codes: 0 pass, 1 regression, 2 unreadable or synthetic report (`example.json` is
  refused), unknown split.
- The baseline is main's committed number, scored on main's Labels. A PR that also changes
  `labels.csv` compares against Labels it no longer has; the table shows n on both sides.

**Fork safety.** The trigger is `pull_request` (never `pull_request_target`), so a fork's
PR gets neither secrets nor a writable token. When the PR comes from a fork, or the secret
is missing (Dependabot, a repository without it), the paid steps are skipped with a
warning and the job **passes ungated**; the summary says so. Gate such a PR by pushing its
commits to a branch of this repository.

**Release tags** (`v*`): `make eval-refresh SPLIT=test` → `make eval SPLIT=test` (the dev
runs already in `latest.json` are kept), a summary of the T1 test numbers, and the artifact
`eval-test-<tag>` (90 days). Without the secret the job fails. Nothing is committed back
(a tag is not a branch, and a bot push to main would bypass review): commit the artifact's
files in a normal PR; that updates `/en/evaluation` and the README badge.

Secret: `ANTHROPIC_API_KEY` (GitHub → Settings → Secrets and variables → Actions). The
workflow has `contents: read` only, one concurrency group per PR (a new push cancels the
running job) and job/step timeouts. It has not run on GitHub yet (no remote).

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
