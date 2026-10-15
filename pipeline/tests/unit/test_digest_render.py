"""Digest email content (spec §10.3, §10.5): en/nl/zh, plain text and HTML that say the
same thing, AI values marked, no promotional content."""

from datetime import UTC, date, datetime

from openfoodalerts.mail.templates import Digest, DigestItem, Label, Summary, render_digest

MANAGE = "https://openfoodalerts.nl/en/alerts/manage/TOKEN"
UNSUBSCRIBE = "https://openfoodalerts.nl/api/unsubscribe?token=TOKEN"


def item(**overrides: object) -> DigestItem:
    values: dict[str, object] = {
        "notification_id": 1,
        "title": "Salmonella in sesame paste from Türkiye",
        "source": "rasff",
        "published_on": date(2026, 10, 24),
        "severity": "serious",
        "hazard_categories": (Label("pathogenic micro-organisms", ai=False),),
        "product_categories": (Label("nuts, nut products and seeds", ai=False),),
        "summary": None,
        "detail_url": "https://openfoodalerts.nl/en/n/rasff/2026.0001",
        "official_url": "https://webgate.ec.europa.eu/rasff-window/screen/notification/1",
    }
    values.update(overrides)
    return DigestItem(**values)  # type: ignore[arg-type]


def digest(locale: str = "en", **overrides: object) -> Digest:
    values: dict[str, object] = {
        "locale": locale,
        "day": date(2026, 10, 25),
        "since": datetime(2026, 10, 24, 5, 0, tzinfo=UTC),
        "new": (item(),),
        "updated": (),
        "news": (),
        "manage_url": MANAGE,
        "unsubscribe_url": UNSUBSCRIBE,
        "site_url": "https://openfoodalerts.nl",
    }
    values.update(overrides)
    return Digest(**values)  # type: ignore[arg-type]


def test_english_digest_lists_each_item_with_its_fields() -> None:
    email = render_digest(digest())
    assert email.subject == "OpenFoodAlerts Digest, 2026-10-25"
    text = email.text
    # The window start is shown in Amsterdam time.
    assert "since 2026-10-24 07:00" in text
    assert "New (1)" in text
    assert "Updated" not in text  # empty sections are left out
    assert "Salmonella in sesame paste from Türkiye" in text
    assert "RASFF · 2026-10-24 · Official severity: serious" in text
    assert "Hazard category: pathogenic micro-organisms" in text
    assert "Product category: nuts, nut products and seeds" in text
    assert "https://openfoodalerts.nl/en/n/rasff/2026.0001" in text
    assert "https://webgate.ec.europa.eu/rasff-window/screen/notification/1" in text
    assert MANAGE in text and UNSUBSCRIBE in text
    assert "openfoodalerts.nl" in text.split("--")[-1]


def test_nvwa_is_not_graded_and_ai_values_are_marked() -> None:
    nvwa = item(
        source="nvwa",
        severity=None,
        hazard_categories=(Label("allergens", ai=True),),
        product_categories=(),
        summary=Summary("Undeclared milk in pokebowl.", ai=True),
    )
    text = render_digest(digest(new=(nvwa,))).text
    assert "NVWA · 2026-10-24 · Official severity: not graded" in text
    assert "Hazard category: allergens (AI)" in text
    assert "AI summary: Undeclared milk in pokebowl." in text
    assert "Product category" not in text


def test_source_text_fallback_is_not_marked_ai() -> None:
    fda = item(
        source="openfda", severity="Class I", summary=Summary("Undeclared peanuts", ai=False)
    )
    text = render_digest(digest(new=(fda,))).text
    assert "Source text: Undeclared peanuts" in text
    assert "AI summary" not in text
    assert "openFDA · 2026-10-24 · Official severity: Class I" in text


def test_sections_and_marks() -> None:
    email = render_digest(
        digest(
            new=(item(sent_instantly=True),),
            updated=(item(notification_id=2, title="Updated one", updated_on=date(2026, 10, 25)),),
            news=(item(notification_id=3, title="News one", severity=None),),
        )
    )
    text = email.text
    assert text.index("New (1)") < text.index("Updated (1)") < text.index("RASFF News (1)")
    assert "[sent instantly]" in text
    assert "Substantial update seen on 2026-10-25" in text
    assert "sent instantly" in email.html
    assert "RASFF News (1)" in email.html


def test_html_escapes_and_links() -> None:
    email = render_digest(digest(new=(item(title="<b>Nuts & bolts</b>"),)))
    assert "<b>Nuts" not in email.html
    assert "&lt;b&gt;Nuts &amp; bolts&lt;/b&gt;" in email.html
    assert 'href="https://openfoodalerts.nl/en/n/rasff/2026.0001"' in email.html
    assert f'href="{MANAGE}"' in email.html
    assert f'href="{UNSUBSCRIBE.replace("&", "&amp;")}"' in email.html
    assert '<html lang="en">' in email.html


def test_dutch_and_chinese() -> None:
    nl = render_digest(digest("nl", new=(item(source="nvwa", severity=None),)))
    assert nl.subject == "OpenFoodAlerts-Digest, 2026-10-25"
    assert "Nieuw (1)" in nl.text
    assert "Officiële ernst: niet ingedeeld" in nl.text
    assert "Afmelden" in nl.text

    zh = render_digest(digest("zh", new=(item(source="nvwa", severity=None, sent_instantly=True),)))
    assert zh.subject == "OpenFoodAlerts 每日 Digest（2026-10-25）"
    assert "新增（1）" in zh.text
    assert "官方严重度：未分级" in zh.text
    assert "已即时发送" in zh.text
    assert "退订" in zh.text
    assert '<html lang="zh-Hans">' in zh.html


def test_no_promotional_content() -> None:
    for locale in ("en", "nl", "zh"):
        email = render_digest(digest(locale))
        for word in ("snelvink", "advert", "广告", "utm_"):
            assert word not in email.text.lower()
            assert word not in email.html.lower()
        assert "<img" not in email.html
