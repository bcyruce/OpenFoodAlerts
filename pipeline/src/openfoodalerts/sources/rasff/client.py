"""RASFF Window backend client with the RASFF rate-limit rules (spec §3.1).

On top of `PoliteClient` (sequential requests, User-Agent, 5xx/network retries):

- at least 3 s between requests (`OFA_RASFF_INTERVAL` overrides it, e.g. 1.5 for the
  one-off local backfill; the scheduled jobs keep 3 s);
- a response with `X-Rate-Limit-Remaining` below 10 pauses 60 s before the next request;
- HTTP 429 is logged, pauses 15 min and is retried (up to 3 times, then
  `RasffRateLimited`);
- HTTP 200 with a body that is not JSON (RASFF once answered a detail with an empty body)
  is logged, pauses 30 s and is retried twice; after that the response is returned and the
  caller decides.

Used by `backfill-rasff`; `ingest-rasff` and `refresh-rasff` (ticket 07) reuse it.
"""

import os
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from openfoodalerts.http import PoliteClient
from openfoodalerts.jobs import log_event
from openfoodalerts.sources.rasff.lookups import BASE_URL

SEARCH_PATH = "notification/search/consolidated/en/"
DETAIL_PATH = "notification/view/id/{notif_id}/en/"
ITEMS_PER_PAGE = 50  # the backend rejects 100 and more

REQUEST_INTERVAL = 3.0
LOW_REMAINING = 10
LOW_REMAINING_PAUSE = 60.0
TOO_MANY_REQUESTS_PAUSE = 15 * 60.0
MAX_429_RETRIES = 3
NOT_JSON_PAUSE = 30.0
MAX_NOT_JSON_RETRIES = 2


def is_json(response: httpx.Response) -> bool:
    try:
        response.json()
    except ValueError:
        return False
    return True


class RasffRateLimited(RuntimeError):
    """RASFF kept answering 429 after the pauses."""


def search_url() -> str:
    return BASE_URL + SEARCH_PATH


def detail_url(notif_id: int | str) -> str:
    return BASE_URL + DETAIL_PATH.format(notif_id=notif_id)


def search_body(
    page: int, items_per_page: int = ITEMS_PER_PAGE, filters: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """List request body: paging under "parameters", filters at the top level."""
    return {"parameters": {"pageNumber": page, "itemsPerPage": items_per_page}, **(filters or {})}


class RasffClient:
    def __init__(self, http: PoliteClient) -> None:
        self.http = http

    @classmethod
    def create(
        cls,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> "RasffClient":
        return cls(
            PoliteClient(
                min_interval=float(os.environ.get("OFA_RASFF_INTERVAL") or REQUEST_INTERVAL),
                transport=transport,
                sleep=sleep,
                clock=clock,
            )
        )

    def __enter__(self) -> "RasffClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.http.close()

    @property
    def request_count(self) -> int:
        return self.http.request_count

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        for attempt in range(MAX_NOT_JSON_RETRIES + 1):
            response = self._request_rate_limited(method, url, **kwargs)
            if response.status_code != 200 or is_json(response):
                return response
            log_event("rasff_body_not_json", url=url, attempt=attempt + 1)
            if attempt < MAX_NOT_JSON_RETRIES:
                self.http.pause(NOT_JSON_PAUSE)
        return response

    def _request_rate_limited(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        for attempt in range(MAX_429_RETRIES + 1):
            response = self.http.request(method, url, **kwargs)
            if response.status_code != 429:
                self._respect_remaining(response)
                return response
            log_event(
                "rasff_rate_limited",
                url=url,
                attempt=attempt + 1,
                pause_s=TOO_MANY_REQUESTS_PAUSE if attempt < MAX_429_RETRIES else 0,
            )
            if attempt < MAX_429_RETRIES:
                self.http.pause(TOO_MANY_REQUESTS_PAUSE)
        raise RasffRateLimited(f"{method} {url}: HTTP 429 after {MAX_429_RETRIES} pauses")

    def _respect_remaining(self, response: httpx.Response) -> None:
        header = response.headers.get("X-Rate-Limit-Remaining")
        try:
            remaining = int(header) if header is not None else None
        except ValueError:
            remaining = None
        if remaining is not None and remaining < LOW_REMAINING:
            log_event("rasff_rate_limit_low", remaining=remaining, pause_s=LOW_REMAINING_PAUSE)
            self.http.pause(LOW_REMAINING_PAUSE)

    def search(
        self,
        page: int,
        items_per_page: int = ITEMS_PER_PAGE,
        filters: Mapping[str, Any] | None = None,
    ) -> httpx.Response:
        """One list page (`POST notification/search/consolidated/en/`)."""
        return self._request("POST", search_url(), json=search_body(page, items_per_page, filters))

    def detail(self, notif_id: int | str) -> httpx.Response:
        """One notification detail (`GET notification/view/id/{notifId}/en/`)."""
        return self._request("GET", detail_url(notif_id))
