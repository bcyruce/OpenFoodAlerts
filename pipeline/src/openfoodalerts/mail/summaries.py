"""The one-line summary of a Notification in Digest and Instant emails (spec §10.3).

- RASFF: its `subject`, which is already the item's title (the parser stores subject as
  `title`), so no separate line is shown. T6 never runs for RASFF (spec §6.1).
- NVWA and FDA: the T6 AI summary in the Subscription's language (ticket 18), marked AI.
- Without one (not summarized yet, abstained, no grant): a line of source text, *not*
  marked AI, labelled as source text: NVWA `summary_source` (the page's intro, Dutch),
  FDA `hazard_text` (the reason for recall, English).

`ai_summaries` reads the T6 rows; choosing it over the fallback and the AI label are in
the templates.
"""

import re
from collections.abc import Sequence

from openfoodalerts.classify.summary import summary_task_name
from openfoodalerts.db.connection import Connection
from openfoodalerts.mail.templates import Summary

MAX_CHARS = 200


# T6 rows (ticket 18, `classify.summary`): one task per language, task 'summary_{locale}',
# value {"locale": "nl", "summary": "..."} (summary null when abstained). The newest row
# per (Notification, task) is the current one, and its effective value counts
# (`ai_effective_value`, ticket 20, = classify.effective.effective_value): a reviewer's
# correction wins, also on an abstained row; a model or reviewer abstain means no summary
# (rather than an older summary of an older text).
_T6_SQL = """
SELECT notification_id, ai_effective_value(current) ->> 'summary' AS summary
FROM (
    SELECT DISTINCT ON (notification_id) *
    FROM ai_classifications
    WHERE task = %s AND notification_id = ANY(%s)
    ORDER BY notification_id, created_at DESC, id DESC
) AS current
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
    rows = conn.execute(_T6_SQL, (summary_task_name(locale), list(notification_ids))).fetchall()
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
