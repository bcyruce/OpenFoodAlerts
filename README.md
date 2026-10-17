# OpenFoodAlerts

[![CI](https://github.com/bcyruce/OpenFoodAlerts/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/bcyruce/OpenFoodAlerts/actions/workflows/ci.yml)
[![T1 macro-F1 (test)](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fbcyruce%2FOpenFoodAlerts%2Fmain%2Feval%2Fresults%2Fbadge.json)](https://openfoodalerts.nl/en/evaluation)

A free, open data product that archives official food-safety Notifications from EU RASFF, the Dutch NVWA and US openFDA, puts them on one RASFF-based taxonomy, and fills in missing fields with an openly evaluated AI layer.

Work in progress. See the [v1 spec](docs/spec.md), the [glossary](GLOSSARY.md), the [ADRs](docs/adr/) and the [tickets](docs/tickets/README.md).

## Evaluation

The AI layer is scored on a hand-labelled set of 300 Notifications ([eval/](eval/README.md)) against two baselines, per Source, with bootstrap confidence intervals, a coverage–accuracy curve, annotator agreement and an audit of the official RASFF categories. The website's [/en/evaluation](https://openfoodalerts.nl/en/evaluation) page is generated from [`eval/results/latest.json`](eval/results/latest.json) at every deployment, with its limitations. Status: labelling is in progress, so there are no numbers yet (the badge says "no labels yet"). Reproduce offline, without an API key: `make eval` (dev) or `make eval SPLIT=test`.

The badge is a [shields.io endpoint](https://shields.io/badges/endpoint-badge) reading [`eval/results/badge.json`](eval/results/badge.json), which `make eval` writes next to `latest.json` (overall T1 macro-F1 on the frozen test split of every model run). A fork that publishes elsewhere replaces `bcyruce/OpenFoodAlerts` in the two badge URLs (the website reads the same repository from `OFA_REPO_URL`).

## Local development

Requirements: Docker, [uv](https://docs.astral.sh/uv/), [pnpm](https://pnpm.io/), [dbmate](https://github.com/amacneil/dbmate), GNU make.

```sh
cp .env.example .env
docker compose up -d
make setup
cd pipeline && uv run ofa --help
```

`make help` lists the other targets. For the website with sample data: `make web-fixtures dev`, then open http://localhost:3000/en/n/openfda/H-0015-2027 (see [web/README.md](web/README.md)).

## License

Code: Apache-2.0. Data published in `eval/`: CC BY 4.0.
