"""A fake RASFF Window backend serving the real detail fixtures (shared by RASFF job tests).

List pages honour the `ecValidDateFrom` filter the way the live backend does (ticket 07);
detail bodies carry an `additionalInformations` contact, as live ones do.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from openfoodalerts.sources.rasff.client import RasffClient

FIXTURES = Path(__file__).parent / "fixtures" / "rasff"
DETAILS = FIXTURES / "details"
CONTACT = [{"contactPerson": {"email": "officer@authority.example"}}]
RASFF_TIME = "%d-%m-%Y %H:%M:%S"


def load_detail(path: Path) -> dict[str, Any]:
    body: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return body


class FakeRasff:
    """List pages in fixture order, details by notifId."""

    def __init__(self) -> None:
        bodies = [load_detail(p) for p in sorted(DETAILS.glob("*.json"))]
        self.details: dict[int, dict[str, Any]] = {
            b["id"]: b | {"additionalInformations": CONTACT} for b in bodies
        }
        self.detail_requests: list[int] = []
        self.list_requests: list[dict[str, Any]] = []
        self.missing: set[int] = set()
        self.broken: set[int] = set()  # answer HTTP 500 every time
        self.interrupt_after: int | None = None

    def serve(self, body: dict[str, Any]) -> None:
        """Serve this detail body (e.g. an updated version) from now on."""
        self.details[body["id"]] = body | {"additionalInformations": CONTACT}

    def _listed(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        since = body.get("ecValidDateFrom")
        start = datetime.strptime(since, RASFF_TIME) if since else None
        return [
            {"notifId": i, "reference": d["reference"], "ecValidationDate": d["ecValidationDate"]}
            for i, d in self.details.items()
            if start is None or datetime.strptime(d["ecValidationDate"], RASFF_TIME) >= start
        ]

    def _list(self, body: dict[str, Any]) -> httpx.Response:
        self.list_requests.append(body)
        page, size = body["parameters"]["pageNumber"], body["parameters"]["itemsPerPage"]
        items = self._listed(body)
        chunk = items[(page - 1) * size : page * size]
        pages = -(-len(items) // size)
        return httpx.Response(
            200,
            json={"notifications": chunk, "totalPages": pages, "totalElements": len(items)},
            headers={"X-Rate-Limit-Remaining": "49"},
        )

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return self._list(json.loads(request.content))
        notif_id = int(request.url.path.rstrip("/").split("/")[-2])
        if self.interrupt_after is not None and len(self.detail_requests) >= self.interrupt_after:
            raise KeyboardInterrupt
        self.detail_requests.append(notif_id)
        if notif_id in self.missing:
            return httpx.Response(404, json={"status": "NOT_FOUND"})
        if notif_id in self.broken:
            return httpx.Response(500)
        return httpx.Response(
            200, json=self.details[notif_id], headers={"X-Rate-Limit-Remaining": "49"}
        )

    def client(self) -> RasffClient:
        return RasffClient.create(transport=httpx.MockTransport(self.handler), sleep=lambda s: None)
