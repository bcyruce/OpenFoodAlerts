# Ingest RASFF and NVWA through their undocumented website backends

Neither Source offers an official API or feed: the European Commission provides no public RASFF API, and NVWA's RSS feeds have been offline since the 2026 site relaunch. We therefore call the same backends their own websites use — the RASFF Window public JSON endpoints (list, detail, lookups) and the NVWA site search API plus server-rendered detail pages — and accept that they can change without notice.

We limit the damage by archiving every raw response, running a daily contract probe per Source, and being a polite, identifiable client (sequential requests, an identifying User-Agent, honouring the rate-limit headers).

## Considered Options

- **Paid scraping services (e.g. Apify actors):** cheap per record, but a dependency on a third party that uses the same undocumented endpoints, so no more stable. Kept as a fallback.
- **Headless-browser scraping:** unnecessary, since both backends answer plain HTTP requests, and more fragile.
