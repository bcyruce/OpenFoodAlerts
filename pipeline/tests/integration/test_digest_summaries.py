"""The one-line summary seam (spec §10.3): T6 AI summaries once ticket 18 writes them,
source text (not marked AI) until then."""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from openfoodalerts.db.connection import Connection
from openfoodalerts.mail.summaries import ai_summaries, one_line, summary_line
from openfoodalerts.mail.templates import Summary
from tests.mail_data import add_notification

T = datetime(2026, 10, 24, 8, 0, tzinfo=UTC)


def test_one_line_takes_the_first_paragraph_and_cuts_at_a_word() -> None:
    assert one_line("  Eerste  regel\nloopt door.\n\nTweede alinea.") == "Eerste regel loopt door."
    assert one_line(None) is None
    assert one_line(" \n ") is None
    long = "word " * 60
    cut = one_line(long, limit=50)
    assert cut is not None and cut.endswith("…") and len(cut) <= 50
    assert not cut[:-1].endswith(" ")


def test_summary_line_per_source() -> None:
    # RASFF: the subject is the title already.
    assert summary_line("rasff", ai_text=None, summary_source="x", hazard_text="y") is None
    assert summary_line("nvwa", ai_text=None, summary_source="Intro.", hazard_text=None) == Summary(
        "Intro.", ai=False
    )
    assert summary_line("openfda", ai_text=None, summary_source=None, hazard_text="Reason") == (
        Summary("Reason", ai=False)
    )
    assert summary_line("nvwa", ai_text="AI text", summary_source="Intro.", hazard_text=None) == (
        Summary("AI text", ai=True)
    )
    assert summary_line("openfda", ai_text=None, summary_source=None, hazard_text=None) is None


def test_no_ai_summaries_while_ai_classifications_does_not_exist(db: Connection) -> None:
    nid = add_notification(db, "nvwa", "/a", first_seen_at=T)
    assert ai_summaries(db, [nid], "nl") == {}
    assert ai_summaries(db, [], "nl") == {}


@pytest.fixture
def t6_table(db: Connection) -> Iterator[Connection]:
    """A stand-in for ticket 16/18's table, with the columns of spec §4.1 used here."""
    db.execute(
        """
        CREATE TABLE ai_classifications (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            notification_id bigint NOT NULL, task text NOT NULL, value jsonb,
            abstained boolean NOT NULL DEFAULT false, reviewed_value jsonb,
            created_at timestamptz NOT NULL DEFAULT now())
        """
    )
    db.commit()
    try:
        yield db
    finally:
        db.rollback()
        db.execute("RESET ROLE")
        db.execute("DROP TABLE ai_classifications")
        db.commit()


def test_t6_summaries_in_the_subscriptions_language(t6_table: Connection) -> None:
    db = t6_table
    nid = add_notification(db, "nvwa", "/a", first_seen_at=T)
    other = add_notification(db, "nvwa", "/b", first_seen_at=T)
    rows = [
        (nid, '{"locale": "nl", "summary": "Oud."}', False, None, "2026-10-24T08:00Z"),
        (nid, '{"locale": "nl", "summary": "Nieuw."}', False, None, "2026-10-24T09:00Z"),
        (nid, '{"locale": "en", "summary": "English."}', False, None, "2026-10-24T09:00Z"),
        (
            other,
            '{"locale": "nl", "summary": "Fout."}',
            False,
            '{"locale": "nl", "summary": "Goed."}',
            "2026-10-24T09:00Z",
        ),
        (other, '{"locale": "en"}', True, None, "2026-10-24T10:00Z"),
    ]
    for row in rows:
        db.execute(
            "INSERT INTO ai_classifications (notification_id, task, value, abstained,"
            " reviewed_value, created_at) VALUES (%s, 't6_summary', %s, %s, %s, %s)",
            row,
        )
    assert ai_summaries(db, [nid, other], "nl") == {nid: "Nieuw.", other: "Goed."}
    assert ai_summaries(db, [nid, other], "en") == {nid: "English."}
    # Not granted to ofa_mailer: no summaries rather than a failed Digest.
    db.execute("SET ROLE ofa_mailer")
    assert ai_summaries(db, [nid], "nl") == {}
