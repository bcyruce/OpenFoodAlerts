"""The one-line summary of a Notification in Digest and Instant emails (spec §10.3).

- RASFF: its `subject`, which is already the item's title (the parser stores subject as
  `title`), so no separate line is shown. T6 never runs for RASFF (spec §6.1).
- NVWA and FDA: the T6 AI summary in the Subscription's language, marked AI.
- Until T6 exists (ticket 18): a line of source text, *not* marked AI, labelled as source
  text: NVWA `summary_source` (the page's intro, Dutch), FDA `hazard_text` (the reason
  for recall, English).

`ai_summaries` is the single seam ticket 18 fills in; everything else (choosing it over
the fallback, the AI label in the templates) is already wired.
"""

import re
from collections.abc import Sequence

from openfoodalerts.db.connection import Connection
from openfoodalerts.mail.templates import Summary

MAX_CHARS = 200


# Proposed T6 row shape (spec §4.1 ai_classifications); ticket 18 may change it, and only
# this query has to follow: task 't6_summary', value {"locale": "nl", "summary": "..."},
# a reviewer's correction in reviewed_value (same shape) wins, abstained rows are skipped,
# the newest row per (notification, locale) counts.
_T6_SQL = """
SELECT DISTINCT ON (notification_id) notification_id,
    COALESCE(reviewed_value, value) ->> 'summary' AS summary
FROM ai_classifications
WHERE task = 't6_summary' AND NOT abstained
  AND notification_id = ANY(%s) AND COALESCE(reviewed_value, value) ->> 'locale' = %s
ORDER BY notification_id, created_at DESC
"""


def ai_summaries(conn: Connection, notification_ids: Sequence[int], locale: str) -> dict[int, str]:
    """T6 summaries by Notification id, in `locale` (NVWA: en/nl/zh; FDA: en/nl).

    Empty while `ai_classifications` does not exist or ofa_mailer may not read it (it is
    created by ticket 16; ticket 18 writes T6 rows and must GRANT SELECT to ofa_mailer).
    """
    if not notification_ids:
        return {}
    row = conn.execute(
        # NULL (no such table) passes through the strict function: false.
        "SELECT COALESCE(has_table_privilege(to_regclass('public.ai_classifications'),"
        " 'SELECT'), false) AS ok"
    ).fetchone()
    if row is None or not row["ok"]:
        return {}
    rows = conn.execute(_T6_SQL, (list(notification_ids), locale)).fetchall()
    return {r["notification_id"]: r["summary"] for r in rows if r["summary"]}


def one_line(text: str | None, limit: int = MAX_CHARS) -> str | None:
    """The first paragraph of a text, whitespace collapsed, cut at a word near `limit`."""
    if not text:
        return None
    first = re.split(r"\n\s*\n", text.strip(), maxsplit=1)[0]
    line = " ".join(first.split())
    if not line:
        return None
    if len(line) <= limit:
        return line
    cut = line[: limit - 1]
    if " " in cut[limit // 2 :]:
        cut = cut[: cut.rindex(" ")]
    return cut.rstrip(" ,;:.") + "…"


def summary_line(
    source: str, *, ai_text: str | None, summary_source: str | None, hazard_text: str | None
) -> Summary | None:
    if source == "rasff":
        return None
    if ai_text:
        return Summary(ai_text, ai=True)
    fallback = one_line(summary_source if source == "nvwa" else hazard_text)
    return Summary(fallback, ai=False) if fallback else None
