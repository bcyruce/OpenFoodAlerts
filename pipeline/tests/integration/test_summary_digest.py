"""T6 summaries reach the Digest (spec §10.3): written by `classify_notifications`, read by
`send_digest` as ofa_mailer in the Subscription's language, marked AI."""

from datetime import UTC, datetime, timedelta

import pytest

from openfoodalerts.classify.fake import KeywordClassifier
from openfoodalerts.classify.job import classify_notifications
from openfoodalerts.classify.prompts import load_prompt
from openfoodalerts.classify.summary import SummaryTask
from openfoodalerts.db.connection import Connection
from openfoodalerts.eval.labelset import default_taxonomy_path, load_taxonomy
from openfoodalerts.mail.digest import DigestSettings, send_digest
from openfoodalerts.mail.transport import MemoryTransport
from tests.mail_data import add_notification, add_subscription

pytestmark = pytest.mark.db

NOW = datetime(2026, 10, 25, 6, 0, tzinfo=UTC)
CONFIRMED = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
SETTINGS = DigestSettings(site_url="https://openfoodalerts.nl", token_secret="secret-1")
INTRO = "Melkunie roept Protein Pudding terug omdat er glas in kan zitten."


def summarize(db: Connection, locale: str) -> None:
    fake = KeywordClassifier(load_taxonomy(default_taxonomy_path()))
    task = SummaryTask(locale)
    classify_notifications(
        db, task=task, prompt=load_prompt(task.name), model="fake", make_classifier=lambda: fake
    )


def digest_text(db: Connection) -> dict[str, str]:
    db.commit()
    db.execute("SET ROLE ofa_mailer")
    db.commit()
    transport = MemoryTransport()
    send_digest(db, transport, SETTINGS, now=NOW)
    return {m.to: m.text for m in transport.sent}


def test_each_subscription_gets_the_ai_summary_in_its_language(db: Connection) -> None:
    for locale in ("en", "nl", "zh"):
        add_subscription(
            db,
            f"{locale}@example.com",
            confirmed_at=CONFIRMED,
            locale=locale,
            filters={"sources": ["nvwa"]},
        )
    add_notification(
        db,
        "nvwa",
        "/actueel/nieuws/2026/10/24/x",
        first_seen_at=NOW - timedelta(hours=2),
        title="Veiligheidswaarschuwing Melkunie Protein Pudding",
        summary_source=INTRO,
    )
    db.commit()
    for locale in ("en", "zh"):  # no Dutch summary yet
        summarize(db, locale)
    texts = digest_text(db)
    assert "AI summary: Fake summary for testing" in texts["en@example.com"]
    assert "AI 生成摘要：测试用假模型摘要" in texts["zh@example.com"]
    assert INTRO not in texts["en@example.com"] and INTRO not in texts["zh@example.com"]
    # without a summary in its language, the source text, not marked AI
    assert f"Brontekst: {INTRO}" in texts["nl@example.com"]
    assert "AI-samenvatting" not in texts["nl@example.com"]
