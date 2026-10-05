"""Job runs: one structured JSON log line per run and Source health bookkeeping (spec §5, §13)."""

import json
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Any

from openfoodalerts.db.connection import Connection
from openfoodalerts.http import PoliteClient


@dataclass
class JobStats:
    job: str
    source: str | None
    requests: int = 0
    new: int = 0
    changed: int = 0
    unchanged: int = 0
    errors: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def count(self, status: str) -> None:
        """Count an archive or parse outcome ("new", "changed" or "unchanged")."""
        setattr(self, status, getattr(self, status) + 1)


def log_event(event: str, **fields: Any) -> None:
    sys.stderr.write(json.dumps({"event": event, **fields}, default=str) + "\n")
    sys.stderr.flush()


@contextmanager
def run_job(
    conn: Connection, job: str, source: str | None, client: PoliteClient | None = None
) -> Iterator[JobStats]:
    """Run a job body; afterwards log the run and update the Source's health columns.

    On failure the open transaction is rolled back, `last_error` is recorded and the
    exception propagates.
    """
    stats = JobStats(job=job, source=source)
    started = time.monotonic()
    requests_before = client.request_count if client else 0
    status = "ok"
    try:
        yield stats
    except BaseException as exc:
        status = "error"
        message = f"{type(exc).__name__}: {exc}"
        stats.errors.append(message)
        conn.rollback()
        if source is not None:
            conn.execute(
                "UPDATE sources SET last_error = %s, last_error_at = now() WHERE code = %s",
                (message, source),
            )
        conn.commit()
        raise
    else:
        if source is not None:
            conn.execute("UPDATE sources SET last_success_at = now() WHERE code = %s", (source,))
        conn.commit()
    finally:
        if client is not None:
            stats.requests = client.request_count - requests_before
        record = asdict(stats)
        extra = record.pop("extra")
        log_event(
            "job_finished",
            status=status,
            duration_s=round(time.monotonic() - started, 3),
            **record,
            **extra,
        )
