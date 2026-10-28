# OpenFoodAlerts data card

> Draft, version 2026-10-25. This file is the source of truth for the data card; the website renders it at [/data](https://openfoodalerts.nl/en/data) together with the taxonomy table from the CSV. Sections are extended as the corresponding tickets land (ticket 27 owns this file). Licence statements marked "to be verified" are checked before launch (spec §16 V4, V5).

OpenFoodAlerts archives the food-safety Notifications that three official Sources publish, puts them into one schema, and adds an AI layer that fills in the classification fields two of the Sources lack. OpenFoodAlerts is not an official source and is not affiliated with or endorsed by the European Commission, NVWA or FDA. Always check the official Notification before acting on it.

## Sources

| Source | Publisher | What we collect | Licence | Attribution shown with every Notification |
|---|---|---|---|---|
| [RASFF Window](https://webgate.ec.europa.eu/rasff-window/) | European Commission, Rapid Alert System for Food and Feed | Every public Notification (alert, border rejection, information for attention, information for follow-up, non-compliance; News when published) with its Hazards, Product categories, countries and measures | CC BY 4.0 (Commission Decision 2011/833/EU; RASFF-specific terms to be verified) | Source: European Commission – RASFF Window; normalized and classified by OpenFoodAlerts, changes indicated. |
| [NVWA veiligheidswaarschuwingen](https://www.nvwa.nl/) | Nederlandse Voedsel- en Warenautoriteit | Every safety warning ("veiligheidswaarschuwing"): title, summary, product details, update notes, links to recall pages | CC0 1.0 for text (photos and videos excluded) | Source: Nederlandse Voedsel- en Warenautoriteit (NVWA). Unofficial; not endorsed by NVWA. |
| [openFDA food enforcement reports](https://open.fda.gov/apis/food/enforcement/) | U.S. Food and Drug Administration | Every food enforcement (recall) report with its classification, status, recalling firm, distribution pattern and dates | US federal public domain (CC0 claim to be verified) | Source: U.S. Food and Drug Administration via openFDA. Not endorsed by FDA. |

Licence notes:

- **RASFF.** The Commission's reuse policy (Decision 2011/833/EU) allows reuse of its documents with attribution, and CC BY 4.0 is the Commission's default licence under that policy. We found no terms specific to RASFF Window; this is being verified (V4). We indicate our changes: Hazard names are split from their category, dates are converted to UTC, and AI classifications are always marked as such.
- **NVWA.** The pages carry `DCTERMS.rights: CC0 1.0`, which does not cover photos and videos. We reuse the text only and never copy images (they often belong to the retailer).
- **openFDA.** Works of the US federal government are in the public domain; openFDA's statement that its data are CC0 is being verified (V5). We do not imply any FDA endorsement.

## Coverage

| Source | Period available | Updates | Notes |
|---|---|---|---|
| RASFF Window | Since 2012 (the oldest Notification in the public list is 2012.0101); 33,146 Notifications in the list on 2026-10-24 | List every 6 hours (last 14 days); details of the last 30 days re-read daily | The full backfill (ticket 08) has not run yet, so the archive covers recent Notifications only for now. RASFF News: none could be retrieved from the public list so far (V12). |
| NVWA | Since 2023-10-04 (570 warnings on 2026-10-25: 504 in the archive before 2026-07-01, 66 in the new list) | Every 2 hours; changed pages are found through the sitemap | No usable source for earlier warnings has been found (V9). The warnings topic also contains non-food warnings (car seats, toys, power banks…). |
| openFDA | Since June 2012 (oldest `report_date` 2012-06-20); 29,505 reports on 2026-10-24 | Weekly snapshots, checked daily | FDA changes `status` and `classification` of older reports afterwards; every change is kept as a version. |

All timestamps are stored as UTC and shown in Europe/Amsterdam time. RASFF dates carry no time zone and are read as Europe/Brussels time (to be verified, V2); FDA dates are calendar days.

## Fields

Every Notification has these fields, whatever its Source. Values copied from the Source are *official*; values the AI layer adds are *AI classifications* and are always kept and shown apart.

| Field | Meaning |
|---|---|
| Source, source key | `rasff` with the RASFF reference (e.g. 2026.9489), `nvwa` with the URL path of the warning, `openfda` with the recall number |
| Source URL | The official page (openFDA has none per report: an API query for the recall number) |
| Title | RASFF subject, NVWA page title, or the first part of the FDA product description |
| Published, Source updated | The Source's own dates |
| First seen, last changed | When OpenFoodAlerts first archived the Notification and last saw a change |
| Notification type | The Source's own kind: RASFF classification, NVWA safety warning, FDA enforcement report |
| Official severity | RASFF risk decision or FDA classification (Class I–III). NVWA does not grade its warnings: shown as "not graded" |
| Status | Official status where the Source has one (FDA ongoing / completed / terminated; NVWA withdrawn warnings) |
| Product type | food (including food supplements), feed, food contact material or non-food, with how it was decided (official, rule or AI) |
| Product, Hazard, summary | Product text, Hazard text and the Source's own summary paragraph, in the Source's language |
| Hazards | RASFF: each Hazard with its Hazard category, analytical result, unit, maximum permitted level and sampling date |
| Product categories, countries | RASFF Product categories; countries with their role (origin, notifying, distribution, operator; FDA recalling firm) |
| Measures | RASFF only: action taken, by country |
| Source fields | Other official fields of one Source, such as FDA's recalling firm, distribution pattern and dates, or NVWA's product details (best before, EAN, batch) |
| Versions | Every observed change, with the fields that changed and whether it was substantial |
| AI classifications | Primary hazard category, Product category, Hazard, country of origin, Product type and summary, each with model, prompt version, taxonomy version and confidence |

Never published: the RASFF contact details of authorities (`additionalInformations`) stay in the raw archive only; NVWA images are not copied; subscription data are private and in no export.

## Methods

### Ingestion

Each Source is read by a scheduled job that sends requests one at a time, identifies itself (`OpenFoodAlerts-bot/1.0 (+https://openfoodalerts.nl/about)`), honours rate limits and retries server errors with exponential backoff. RASFF and NVWA offer no official API, so we use the same backends their websites use ([ADR 0002](adr/0002-undocumented-source-endpoints.md)); openFDA has an official API. Every raw response is stored before it is parsed, in an append-only archive that is never changed ([ADR 0004](adr/0004-append-only-raw-archive.md)), so the data can always be parsed again without fetching it again. A daily contract probe per Source checks that the responses still have the expected structure; when they do not, parsing for that Source stops until the parser is fixed, while archiving continues.

### Versioning

Every parse compares the normalised fields with the current version. Any difference becomes a new version with the changed fields; detail pages show the history. A change is *substantial* (and appears in the Digest as an update) when:

- RASFF: a distribution country is added or the risk decision changes;
- NVWA: a new update note appears at the top of the warning;
- FDA: the classification is raised (III → II → I) or the distribution pattern changes.

Other changes, such as an FDA report becoming terminated or a corrected text, are only kept in the version history. When a parser improves, all Notifications are rebuilt from the archive.

### Product type

| Source | Rule |
|---|---|
| RASFF | Official product type: food → food; feed → feed; food contact material → food contact material; animals and other → non-food |
| NVWA | Keyword rules on title, summary and product lines decide clear food and non-food cases; everything else (food contact material, feed, conflicting signals) goes to the AI layer (T5) |
| openFDA | Food by default (food supplements count as food, as in RASFF); pet food → feed; cosmetics keywords → non-food; unclear cases go to T5 |

### Scope and exclusion rules

- **Non-food** Notifications are archived only: they appear on no page, in no statistic, Digest or Instant email, and are not classified by T1–T4 or T6. The same applies while the Product type is still undecided.
- **Statistics** (dashboard, home page charts) count food, feed and food contact material, and leave out RASFF News. Search and detail pages show RASFF News.
- Statistics are always **per Source** and never deduplicated across Sources: the same incident can appear in several Sources ([ADR 0005](adr/0005-relate-not-merge-across-sources.md)).
- About a quarter of public RASFF details list no Hazard at all, even for clear cases; counts by Hazard category are therefore lower bounds.

### AI layer

For NVWA and openFDA, which publish no structured classification, an AI layer adds a Primary hazard category (T1), a Product category (T2), the Hazard as quoted in the text (T3), the country of origin only when the text states it (T4), the Product type where rules cannot decide (T5) and a neutral summary of at most 40 words (T6, not for RASFF). The model may abstain. Every AI value is shown with a badge, links to the [evaluation](https://openfoodalerts.nl/en/evaluation) and to the official text, and can be switched off with "official classification only". The AI never infers severity or facts ([ADR 0006](adr/0006-llm-never-infers-severity-or-facts.md)).

The evaluation uses a hand-labelled set of 300 Notifications (NVWA 120, FDA 120, RASFF 60; dev 100 / test 200), labelled by a food-safety expert, and a RASFF silver set of 2,000 Notifications since 2020 whose Hazards all fall in one category, with the official category as reference and only the subject as model input. The share of RASFF Notifications excluded from the silver set because their Hazards fall into more than one category is given under [Eval set and RASFF silver set](#eval-set-and-rasff-silver-set-draft-ticket-12) (draft numbers on a small local sample until the full backfill).

## Taxonomy v1 (draft, not frozen)

The AI layer's T1 label set comes from RASFF's 30 current Hazard categories ([ADR 0003](adr/0003-rasff-taxonomy-single-primary-hazard.md), spec §6.2):

1. "GMO / novel food", "genetically modified" and "novel food" become one label, **GMO / novel food**.
2. Categories with fewer than 30 RASFF Notifications since 2020-01-01 fold into **other**.

Counts come from the RASFF Window list endpoint filtered by Hazard category, `ecValidDateFrom = 01-01-2020` and product type food / feed / food contact material (`ofa taxonomy-draft`, run 2026-10-25). A Notification whose Hazards fall into several categories counts in each. About a quarter of public RASFF details list no Hazard at all, so the counts are lower bounds.

The draft table is [`db/seed/taxonomy/v1-draft.csv`](../db/seed/taxonomy/v1-draft.csv): 25 labels plus **other**, 26 in all (GMO / novel food merges three categories; folded into other: packaging defective / incorrect 6, poor or insufficient controls 1, biotoxins (other) 0). The domain expert reviews it before it is frozen as `db/seed/taxonomy/v1.csv` with `taxonomy_version = 1`; after that it changes only through a new version.

<!-- taxonomy-table -->

## Eval set and RASFF silver set (draft, ticket 12)

Format, sampling and labelling are described in [`eval/README.md`](../eval/README.md). Data in `eval/` is CC BY 4.0.

**Hand-labelled eval set** (`eval/items.csv`, sampled 2026-10-25 on the draft taxonomy): 300 Notifications, NVWA 120 / openFDA 120 / RASFF 60, split dev 100 / test 200 (40/80, 40/80, 20/40 per Source), stratified by Source × hazard group (RASFF: official category; NVWA and openFDA: a keyword pre-label, not a Label), one item per FDA recall event. The 60 RASFF items are the official-label noise audit set; 60 items (24/24/12) form the second-annotator agreement subset. Every T1 label should have ≥ 8 items, but 300 = 120/120/60 cannot give 26 labels 8 items each when about a dozen hazards occur almost only in RASFF: on the local data 10 labels stay below 8 (migration 3, natural toxins (other) 5, environmental pollutants 5, GMO / novel food 3, industrial contaminants 4, residues of veterinary medicinal products 7, not determined (other) 2, TSEs 3, adulteration / fraud 3, feed additives 3; see `shortfall` in `eval/sampling.json`). Label floors over-sample rare hazards on purpose; `eval/sampling.json` keeps frame sizes and allocation per stratum for reweighting.

**RASFF silver set** (`eval/silver.csv`): RASFF Notifications since 2020 (food, feed, food contact material; no News) whose official Hazards all map to one T1 label, stratified by label, at most 2,000, eval items left out. Excluded because their Hazards span several labels (local data, 2026-10-25, before the full backfill, so **n is small**):

| Local RASFF data | Notifications | without any Hazard | with Hazards | several T1 labels (excluded) | several raw RASFF categories |
|---|---|---|---|---|---|
| Contiguous window 2026-10-20 … 23 | 100 | 24 | 76 | 0 (0.0%; 95% upper bound ≈ 4%) | 0 |
| All local, incl. 48 fetched for rare categories | 148 | 24 | 124 | 1 (0.8%) | 1 |

Shares are of the Notifications that list Hazards. The 48 extra Notifications were picked by Hazard category to fill rare eval labels, so the second row is not a random sample. About a quarter of public RASFF details list no Hazard at all; they cannot enter the silver set either. The local silver set has 64 Notifications (of 2,000 wanted); re-run `ofa eval-silver` after the full backfill (ticket 08) and replace these numbers.

## Reuse

The code is licensed under Apache 2.0 ([LICENSE](../LICENSE)); the evaluation set is published under CC BY 4.0. When you reuse Notifications from OpenFoodAlerts, keep the attribution of the Source shown above and its licence, and mark AI classifications as AI-made. Found an error? Each Notification page has a "report an error" link.
