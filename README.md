# OpenFoodAlerts

A free, open data product that archives official food-safety Notifications from EU RASFF, the Dutch NVWA and US openFDA, puts them on one RASFF-based taxonomy, and fills in missing fields with an openly evaluated AI layer.

Work in progress. See the [v1 spec](docs/spec.md), the [glossary](GLOSSARY.md), the [ADRs](docs/adr/) and the [tickets](docs/tickets/README.md).

## Local development

Requirements: Docker, [uv](https://docs.astral.sh/uv/), [pnpm](https://pnpm.io/), [dbmate](https://github.com/amacneil/dbmate), GNU make.

```sh
cp .env.example .env
docker compose up -d
make setup
cd pipeline && uv run ofa --help
```

`make help` lists the other targets.

## License

Code: Apache-2.0. Data published in `eval/`: CC BY 4.0.
