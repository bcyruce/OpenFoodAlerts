"""Instant email content (spec §10.4, §10.5): one Notification, en/nl/zh, plain text and
HTML, subject naming the source and its official classification, calm wording."""

from datetime import date

import pytest

from openfoodalerts.mail.templates import DigestItem, InstantEmail, Label, Summary, render_instant

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
        "product_categories": (),
        "summary": None,
        "detail_url": "https://openfoodalerts.nl/en/n/rasff/2026.0001",
        "official_url": "https://webgate.ec.europa.eu/rasff-window/screen/notification/1",
    }
    values.update(overrides)
    return DigestItem(**values)  # type: ignore[arg-type]


def instant(
    locale: str = "en", notification_type: str = "alert notification", **kw: object
) -> InstantEmail:
    return InstantEmail(
        locale=locale,
        item=item(**kw),
        notification_type=notification_type,
        manage_url=MANAGE,
        unsubscribe_url=UNSUBSCRIBE,
        site_url="https://openfoodalerts.nl",
    )


def test_english_instant_email_for_a_rasff_alert() -> None:
    email = render_instant(instant())
    assert email.subject == ("RASFF, alert notification: Salmonella in sesame paste from Türkiye")
    text = email.text
    assert "Salmonella in sesame paste from Türkiye" in text
    assert "RASFF · 2026-10-24 · Official severity: serious" in text
    assert "Hazard category: pathogenic micro-organisms" in text
    assert "https://openfoodalerts.nl/en/n/rasff/2026.0001" in text
    assert "https://webgate.ec.europa.eu/rasff-window/screen/notification/1" in text
    assert "next Digest" in text
    assert MANAGE in text and UNSUBSCRIBE in text
    assert "Instant email" in text.split("--")[-1]


def test_the_subject_names_the_official_classification_of_each_source() -> None:
    fda = render_instant(
        instant(
            source="openfda",
            severity="Class I",
            notification_type="enforcement report",
            title="Undeclared peanuts in cookies",
        )
    )
    assert fda.subject == "openFDA, Class I: Undeclared peanuts in cookies"
    nvwa = render_instant(
        instant(source="nvwa", severity=None, notification_type="safety warning", title="Kip")
    )
    assert nvwa.subject == "NVWA, safety warning: Kip"


def test_long_titles_are_shortened_in_the_subject_only() -> None:
    title = "Listeria monocytogenes " * 20
    email = render_instant(instant(title=title.strip()))
    assert len(email.subject) <= 140
    assert email.subject.endswith("…")
    assert title.strip() in email.text


def test_ai_values_are_marked() -> None:
    email = render_instant(
        instant(
            source="nvwa",
            severity=None,
            notification_type="safety warning",
            hazard_categories=(Label("allergens", ai=True),),
            summary=Summary("Undeclared milk.", ai=True),
        )
    )
    assert "Hazard category: allergens (AI)" in email.text
    assert "may be wrong" in email.text


def test_dutch_and_chinese() -> None:
    nl = render_instant(
        instant("nl", source="nvwa", severity=None, notification_type="safety warning", title="Kip")
    )
    assert nl.subject == "NVWA, veiligheidswaarschuwing: Kip"
    assert "Officiële ernst: niet ingedeeld" in nl.text
    assert "Afmelden" in nl.text
    zh = render_instant(
        instant("zh", source="nvwa", severity=None, notification_type="safety warning", title="Kip")
    )
    assert zh.subject == "NVWA 安全警告：Kip"
    assert "官方严重度：未分级" in zh.text
    assert "退订" in zh.text
    assert '<html lang="zh-Hans">' in zh.html


def test_html_escapes() -> None:
    email = render_instant(instant(title="<b>Nuts & bolts</b>"))
    assert "<b>Nuts" not in email.html
    assert "&lt;b&gt;Nuts &amp; bolts&lt;/b&gt;" in email.html
    assert f'href="{MANAGE}"' in email.html


@pytest.mark.parametrize("locale", ["en", "nl", "zh"])
def test_calm_wording_and_no_promotional_content(locale: str) -> None:
    email = render_instant(instant(locale))
    for text in (email.subject, email.text, email.html):
        lowered = text.lower()
        for word in ("snelvink", "advert", "广告", "utm_", "urgent", "danger", "紧急", "dringend"):
            assert word not in lowered
    for mark in ("!", "！"):  # noqa: RUF001
        assert mark not in email.subject + email.text
    assert "<img" not in email.html
