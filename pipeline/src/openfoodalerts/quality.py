"""`check-data`: data quality assertions on the parsed Notifications (spec §12.4).

Each check returns a `CheckResult`; an `error` check that does not hold makes the job
exit non-zero, a `warning` is only reported. Checks cover what is shown on the site
(Product type food, feed or food contact material, spec §4.3):

- `published_at`: every displayed Notification has a publication date.
- `no_future_dates`: no timestamp later than now (+ a small clock tolerance) and no
  calendar date (RASFF sampling date) after today.
- `title_and_source_url`: every displayed Notification has a title and an https link to
  the Source.
- `rasff_hazards_parsed`: a RASFF Notification whose current raw detail lists a Hazard
  has at least one official Hazard row (parser/store fidelity, checked against the raw
  JSON in SQL, independently of the parser).
- `rasff_hazard_coverage`: about a quarter of RASFF details carry no Hazard at all in the
  public data (implementation log, ticket 06 and 10), so "every RASFF Notification has an
  official Hazard" cannot hold. Instead the share without a Hazard among the displayed
  RASFF Notifications of the last 30 days must stay at or below `hazard_max_missing`
  (checked only with at least `hazard_min_sample` Notifications). A jump means RASFF
  stopped publishing Hazards or moved them.
- `rasff_dictionaries` (warning): Hazard or Product categories and countries the seed
  dictionaries do not know; run `ofa seed-rasff-lookups`.
- `openfda_recall_numbers` (warning): openFDA Notifications keyed by a placeholder recall
  number ("" or "N/A").
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from openfoodalerts.db.connection import Connection
from openfoodalerts.jobs import run_job

Severity = Literal["error", "warning"]

CLOCK_TOLERANCE = timedelta(minutes=30)
HAZARD_WINDOW = timedelta(days=30)
HAZARD_MIN_SAMPLE = 20
# Observed 2026-10-25: 24 of 100 recent RASFF details without a Hazard (24 %).
HAZARD_MAX_MISSING = 0.5
MAX_EXAMPLES = 10
EXIT_FAILED = 3

_DISPLAYED_SQL = "n.product_type IN ('food', 'feed', 'food contact material')"
_KEY = "s.code || ':' || n.source_key"


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    summary: str
    severity: Severity = "error"
    examples: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


def _keys(conn: Connection, sql: str, params: dict[str, Any] | None = None) -> list[str]:
    return [str(r["key"]) for r in conn.execute(sql, params or {}).fetchall()]


def _plural(count: int, word: str) -> str:
    return f"{count:,} {word}" + ("" if count == 1 else "s")


def _missing_check(name: str, offenders: list[str], what: str, ok_text: str) -> CheckResult:
    if not offenders:
        return CheckResult(name, True, ok_text)
    return CheckResult(
        name,
        False,
        f"{_plural(len(offenders), 'displayed Notification')} {what}",
        examples=offenders[:MAX_EXAMPLES],
    )


def check_published_at(conn: Connection) -> CheckResult:
    offenders = _keys(
        conn,
        f"""
        SELECT {_KEY} AS key FROM notifications n JOIN sources s ON s.id = n.source_id
        WHERE {_DISPLAYED_SQL} AND n.published_at IS NULL ORDER BY 1
        """,
    )
    return _missing_check(
        "published_at", offenders, "without published_at", "every displayed Notification has one"
    )


def check_title_and_source_url(conn: Connection) -> CheckResult:
    offenders = _keys(
        conn,
        f"""
        SELECT {_KEY} AS key FROM notifications n JOIN sources s ON s.id = n.source_id
        WHERE {_DISPLAYED_SQL}
          AND (btrim(n.title) = '' OR n.source_url NOT LIKE 'https://_%%')
        ORDER BY 1
        """,
    )
    return _missing_check(
        "title_and_source_url",
        offenders,
        "without a title or an https source_url",
        "every displayed Notification has both",
    )


def check_no_future_dates(conn: Connection, now: datetime) -> CheckResult:
    """Timestamps of every Notification (shown or not): a future date is a parsing error."""
    limit = now + CLOCK_TOLERANCE
    today = now.astimezone(UTC).date()
    timestamp_checks = " UNION ALL ".join(
        f"""
        SELECT {_KEY} || ' {col} ' || to_char(n.{col} AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS key
        FROM notifications n JOIN sources s ON s.id = n.source_id WHERE n.{col} > %(limit)s
        """
        for col in ("published_at", "source_updated_at", "first_seen_at", "last_changed_at")
    )
    offenders = _keys(
        conn,
        f"""
        {timestamp_checks}
        UNION ALL
        SELECT DISTINCT {_KEY} || ' sampling_date ' || h.sampling_date::text AS key
        FROM notification_hazards h
        JOIN notifications n ON n.id = h.notification_id JOIN sources s ON s.id = n.source_id
        WHERE h.sampling_date > %(today)s
        ORDER BY 1
        """,
        {"limit": limit, "today": today},
    )
    if not offenders:
        return CheckResult("no_future_dates", True, "no Notification is dated in the future")
    return CheckResult(
        "no_future_dates",
        False,
        f"{_plural(len(offenders), 'date')} in the future",
        examples=offenders[:MAX_EXAMPLES],
    )


_RAW_HAS_HAZARD = """
    jsonb_path_exists(d.j, '$.product.hazards[*].name ? (@.type() == "string")')
    OR jsonb_path_exists(
        d.j, '$.product.relatedProducts[*].hazards[*].name ? (@.type() == "string")')
"""


def check_rasff_hazards_parsed(conn: Connection) -> CheckResult:
    offenders = _keys(
        conn,
        f"""
        SELECT {_KEY} AS key
        FROM notifications n
        JOIN sources s ON s.id = n.source_id
        JOIN raw_records r ON r.id = n.raw_record_id
        CROSS JOIN LATERAL (SELECT convert_from(r.body, 'UTF8')::jsonb AS j) d
        WHERE s.code = 'rasff'
          AND ({_RAW_HAS_HAZARD})
          AND NOT EXISTS (
              SELECT 1 FROM notification_hazards h
              WHERE h.notification_id = n.id AND h.provenance = 'official')
        ORDER BY 1
        """,
    )
    if not offenders:
        return CheckResult(
            "rasff_hazards_parsed",
            True,
            "every Hazard in the RASFF details reached notification_hazards",
        )
    return CheckResult(
        "rasff_hazards_parsed",
        False,
        f"{_plural(len(offenders), 'RASFF Notification')} list Hazards in the raw detail"
        " but have no official Hazard row",
        examples=offenders[:MAX_EXAMPLES],
    )


def check_rasff_hazard_coverage(
    conn: Connection, now: datetime, min_sample: int, max_missing: float
) -> CheckResult:
    rows = conn.execute(
        f"""
        SELECT n.notification_type, n.published_at >= %(since)s AS recent,
               NOT EXISTS (SELECT 1 FROM notification_hazards h
                           WHERE h.notification_id = n.id AND h.provenance = 'official')
                   AS without_hazard
        FROM notifications n JOIN sources s ON s.id = n.source_id
        WHERE s.code = 'rasff' AND {_DISPLAYED_SQL} AND n.notification_type <> 'news'
        """,
        {"since": now - HAZARD_WINDOW},
    ).fetchall()

    def tally(selected: list[dict[str, Any]]) -> dict[str, int]:
        return {
            "notifications": len(selected),
            "without_hazard": sum(1 for r in selected if r["without_hazard"]),
        }

    recent = tally([r for r in rows if r["recent"]])
    by_type = {
        t: tally([r for r in rows if r["notification_type"] == t])
        for t in sorted({r["notification_type"] for r in rows})
    }
    details = {"recent": recent, "overall": tally(rows), "by_type": by_type}
    share = recent["without_hazard"] / recent["notifications"] if recent["notifications"] else 0
    summary = (
        f"{recent['without_hazard']} of {recent['notifications']} displayed RASFF Notifications"
        f" of the last {HAZARD_WINDOW.days} days have no official Hazard ({share:.0%};"
        f" limit {max_missing:.0%}"
    )
    if recent["notifications"] < min_sample:
        return CheckResult(
            "rasff_hazard_coverage",
            True,
            summary + f", not checked below {min_sample} Notifications)",
            details=details,
        )
    return CheckResult(
        "rasff_hazard_coverage", share <= max_missing, summary + ")", details=details
    )


_UNMAPPED = {
    "unmapped_hazard_categories": "hazard categories",
    "unmapped_product_categories": "product categories",
    "unmapped_countries": "countries",
}


def check_rasff_dictionaries(conn: Connection) -> CheckResult:
    rows = conn.execute(
        """
        SELECT n.source_key, n.source_fields FROM notifications n
        JOIN sources s ON s.id = n.source_id
        WHERE s.code = 'rasff' AND n.source_fields ?| %(keys)s ORDER BY n.source_key
        """,
        {"keys": list(_UNMAPPED)},
    ).fetchall()
    examples = [
        f"rasff:{r['source_key']} {label}: {', '.join(r['source_fields'][key])}"
        for r in rows
        for key, label in _UNMAPPED.items()
        if r["source_fields"].get(key)
    ]
    if not examples:
        return CheckResult(
            "rasff_dictionaries", True, "every RASFF value is in the seed dictionaries", "warning"
        )
    return CheckResult(
        "rasff_dictionaries",
        False,
        f"{_plural(len(rows), 'RASFF Notification')} with values missing from the seed"
        " dictionaries (run `ofa seed-rasff-lookups`)",
        "warning",
        examples=examples[:MAX_EXAMPLES],
    )


def check_openfda_recall_numbers(conn: Connection) -> CheckResult:
    """Placeholder recall numbers ("" or "N/A", no digit at all) as Notification keys.

    openFDA publishes some "Not Yet Classified" records before a recall number exists.
    Once FDA assigns one, the record arrives under a new key and the placeholder
    Notification stays behind; several such records would also share one key.
    """
    offenders = _keys(
        conn,
        f"""
        SELECT {_KEY} AS key FROM notifications n JOIN sources s ON s.id = n.source_id
        WHERE s.code = 'openfda' AND n.source_key !~ '[0-9]' ORDER BY 1
        """,
    )
    if not offenders:
        return CheckResult(
            "openfda_recall_numbers", True, "every openFDA key is a recall number", "warning"
        )
    return CheckResult(
        "openfda_recall_numbers",
        False,
        f"{_plural(len(offenders), 'openFDA Notification')} keyed by a placeholder recall"
        ' number ("" or N/A)',
        "warning",
        examples=offenders[:MAX_EXAMPLES],
    )


def check_data(
    conn: Connection,
    *,
    now: datetime | None = None,
    hazard_min_sample: int = HAZARD_MIN_SAMPLE,
    hazard_max_missing: float = HAZARD_MAX_MISSING,
) -> list[CheckResult]:
    """Run every check; read-only. Logs one job line with each check's outcome."""
    now = now or datetime.now(UTC)
    with run_job(conn, "check-data", None) as stats:
        results = [
            check_published_at(conn),
            check_no_future_dates(conn, now),
            check_title_and_source_url(conn),
            check_rasff_hazards_parsed(conn),
            check_rasff_hazard_coverage(conn, now, hazard_min_sample, hazard_max_missing),
            check_rasff_dictionaries(conn),
            check_openfda_recall_numbers(conn),
        ]
        conn.rollback()
        stats.extra["checks"] = {r.name: _mark(r) for r in results}
        stats.extra["failed"] = failed(results)
    return results


def failed(results: list[CheckResult]) -> list[str]:
    """Names of the error checks that do not hold (warnings excluded)."""
    return [r.name for r in results if not r.ok and r.severity == "error"]


def _mark(result: CheckResult) -> str:
    if result.ok:
        return "PASS"
    return "FAIL" if result.severity == "error" else "WARN"


def format_report(results: list[CheckResult]) -> str:
    width = max(len(r.name) for r in results)
    lines = []
    for r in results:
        lines.append(f"{_mark(r)}  {r.name.ljust(width)}  {r.summary}")
        lines.extend(f"    {e}" for e in r.examples)
    return "\n".join(lines)
