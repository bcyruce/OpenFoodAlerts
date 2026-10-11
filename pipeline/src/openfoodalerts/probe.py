"""`probe-contracts` (spec §3.4, §13): one light set of requests per Source, checked
against the Source's contract models; the result is stored per Source.

- `ok`: the responses match. Clears an earlier failure, so `parse` resumes.
- `failed`: a response does not match (`ContractViolation`) or the probe hit an
  unexpected error. `parse` skips the Source until a probe passes again (raw archiving
  continues) and a `contract_check_failed` event is logged.
- `unreachable`: network error, 5xx after retries or RASFF rate limiting. Logged and
  shown on /api/health, but parse is not blocked: it says nothing about the structure.

The probe is read-only towards the Source data: responses are not archived (like
`seed-rasff-lookups`), and it never touches `last_success_at` / `last_error`, which
describe ingest runs (freshness, spec §13).
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

import httpx

from openfoodalerts.contracts import ContractViolation, SourceUnreachable
from openfoodalerts.db.connection import Connection
from openfoodalerts.http import PoliteClient
from openfoodalerts.jobs import log_event, run_job
from openfoodalerts.sources.rasff.client import RasffClient, RasffRateLimited

ContractStatus = Literal["ok", "failed", "unreachable"]
Probe = Callable[[], None]
EXIT_PROBLEMS = 3


@dataclass(frozen=True)
class ContractResult:
    source: str
    status: ContractStatus
    error: str | None = None


def default_probes(
    rasff: RasffClient, nvwa: PoliteClient, openfda: PoliteClient
) -> dict[str, Probe]:
    from openfoodalerts.sources.nvwa import contract as nvwa_contract
    from openfoodalerts.sources.openfda import contract as openfda_contract
    from openfoodalerts.sources.rasff import contract as rasff_contract

    return {
        "rasff": lambda: rasff_contract.probe(rasff),
        "nvwa": lambda: nvwa_contract.probe(nvwa),
        "openfda": lambda: openfda_contract.probe(openfda),
    }


def run_probe(source: str, probe: Probe) -> ContractResult:
    """Run one probe; the stored message never carries URLs, values or bodies."""
    try:
        probe()
    except ContractViolation as exc:
        return ContractResult(source, "failed", str(exc))
    except SourceUnreachable as exc:
        return ContractResult(source, "unreachable", str(exc))
    except (httpx.TransportError, RasffRateLimited) as exc:
        log_event("contract_probe_error", source=source, error=f"{type(exc).__name__}: {exc}")
        return ContractResult(source, "unreachable", type(exc).__name__)
    except Exception as exc:
        log_event("contract_probe_error", source=source, error=f"{type(exc).__name__}: {exc}")
        return ContractResult(source, "failed", f"{type(exc).__name__} (see the job log)")
    return ContractResult(source, "ok")


def _store(conn: Connection, result: ContractResult) -> None:
    conn.execute(
        """
        UPDATE sources
        SET contract_status = %s, contract_checked_at = now(), contract_error = %s
        WHERE code = %s
        """,
        (result.status, result.error, result.source),
    )
    conn.commit()


def probe_contracts(
    conn: Connection,
    probes: Mapping[str, Probe],
    clients: Sequence[PoliteClient | RasffClient] = (),
) -> dict[str, ContractResult]:
    """Probe every given Source (one failing Source does not stop the others).

    `clients` only serve the request count in the job log line.
    """
    results: dict[str, ContractResult] = {}
    with run_job(conn, "probe-contracts", None) as stats:
        for source, probe in probes.items():
            result = run_probe(source, probe)
            _store(conn, result)
            results[source] = result
            if result.status != "ok":
                log_event(
                    "contract_check_failed",
                    source=source,
                    status=result.status,
                    error=result.error,
                )
        stats.extra["contracts"] = {s: r.status for s, r in results.items()}
        stats.requests = sum(c.request_count for c in clients)
    return results


def contract_failed(conn: Connection, source: str) -> bool:
    """True while the last probe found a contract violation for this Source."""
    row = conn.execute("SELECT contract_status FROM sources WHERE code = %s", (source,)).fetchone()
    return row is not None and row["contract_status"] == "failed"
