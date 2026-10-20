"""The one-line summary seam (spec §10.3): T6 AI summaries (ticket 18) where they exist,
source text (not marked AI) otherwise."""

import hashlib
import json
from datetime import UTC, datetime

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
    assert ai_summaries(db, [], "nl") == {}
    # as before ticket 16 created the table
    db.execute("ALTER TABLE ai_classifications RENAME TO ai_classifications_hidden")
    try:
        assert ai_summaries(db, [nid], "nl") == {}
    finally:
        db.rollback()


def add_t6(
    db: Connection,
    nid: int,
    locale: str,
    summary: str | None,
    reviewed: str | None,
    created: str,
) -> None:
    """A T6 row as `ofa classify --task summary_{locale}` writes it (ticket 18): task
    summary_{locale}, value {"locale", "summary"}; an abstain has summary null."""
    value: dict[str, object] = {"locale": locale, "summary": summary}
    if summary is None:
        value |= {"abstain_reason": "too_long", "model_output": {}}
    db.execute(
        "INSERT INTO ai_classifications (notification_id, task, value, abstained, confidence,"
        " reviewed_value, review_status, created_at, model, prompt_version, schema_version,"
        " input_hash) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'm', 'v1', '1', %s)",
        (
            nid,
            f"summary_{locale}",
            json.dumps(value),
            summary is None,
            None if summary is None else "high",
            None if reviewed is None else json.dumps({"locale": locale, "summary": reviewed}),
            "unreviewed" if reviewed is None else "corrected",
            created,
            hashlib.sha256(f"{value}{created}".encode()).hexdigest(),
        ),
    )


def test_t6_summaries_in_the_subscriptions_language(db: Connection) -> None:
    nid = add_notification(db, "nvwa", "/a", first_seen_at=T)
    other = add_notification(db, "nvwa", "/b", first_seen_at=T)
    rows = [
        # the newest row of a (Notification, language) is the current one
        (nid, "nl", "Oud.", None, "2026-10-24T08:00Z"),
        (nid, "nl", "Nieuw.", None, "2026-10-24T09:00Z"),
        (nid, "en", "English.", None, "2026-10-24T09:00Z"),
        # a reviewer's correction wins over the model's text
        (other, "nl", "Fout.", "Goed.", "2026-10-24T09:00Z"),
        (other, "en", None, None, "2026-10-24T10:00Z"),
    ]
    for row in rows:
        add_t6(db, *row)
    db.commit()
    assert ai_summaries(db, [nid, other], "nl") == {nid: "Nieuw.", other: "Goed."}
    assert ai_summaries(db, [nid, other], "en") == {nid: "English."}
    assert ai_summaries(db, [nid, other], "zh") == {}
    db.rollback()


def test_a_current_abstain_hides_an_older_summary_unless_a_reviewer_wrote_one(
    db: Connection,
) -> None:
    changed = add_notification(db, "nvwa", "/a", first_seen_at=T)
    reviewed = add_notification(db, "nvwa", "/b", first_seen_at=T)
    # the text changed and the summary of the new text failed a check: the old summary
    # describes the old text, so the source text is shown instead
    add_t6(db, changed, "zh", "旧摘要。", None, "2026-10-24T08:00Z")
    add_t6(db, changed, "zh", None, None, "2026-10-24T09:00Z")
    # a reviewer may write the summary of an abstained row
    add_t6(db, reviewed, "zh", None, "人工摘要。", "2026-10-24T09:00Z")
    db.commit()
    assert ai_summaries(db, [changed, reviewed], "zh") == {reviewed: "人工摘要。"}


def test_a_reviewer_abstain_hides_the_models_summary(db: Connection) -> None:
    from openfoodalerts.classify.review import correct
    from openfoodalerts.classify.summary import SummaryTask

    nid = add_notification(db, "nvwa", "/a", first_seen_at=T, summary_source="Bevat glas.")
    add_t6(db, nid, "nl", "Bevat glas.", None, "2026-10-24T08:00Z")
    db.commit()
    [row] = db.execute("SELECT id FROM ai_classifications").fetchall()
    correct(db, SummaryTask("nl"), row["id"], None, now=T)
    assert ai_summaries(db, [nid], "nl") == {}
    correct(db, SummaryTask("nl"), row["id"], {"summary": "Het product bevat glas."}, now=T)
    assert ai_summaries(db, [nid], "nl") == {nid: "Het product bevat glas."}


def test_ofa_mailer_reads_summaries_and_a_missing_grant_means_none(db: Connection) -> None:
    nid = add_notification(db, "nvwa", "/a", first_seen_at=T)
    add_t6(db, nid, "nl", "Nieuw.", None, "2026-10-24T09:00Z")
    db.commit()
    # ofa_mailer may read them (granted by ticket 16's migration) ...
    db.execute("SET ROLE ofa_mailer")
    assert ai_summaries(db, [nid], "nl") == {nid: "Nieuw."}
    db.rollback()
    # ... and without the grant there are no summaries rather than a failed Digest.
    db.execute("REVOKE SELECT ON ai_classifications FROM ofa_mailer")
    db.execute("SET ROLE ofa_mailer")
    try:
        assert ai_summaries(db, [nid], "nl") == {}
    finally:
        db.rollback()
