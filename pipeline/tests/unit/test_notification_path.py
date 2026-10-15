"""Detail page paths in emails must equal the website's (web/lib/notification-path.ts);
the examples are the ones in web/lib/notification-path.test.ts."""

from openfoodalerts.mail.paths import notification_path


def test_puts_an_openfda_recall_number_in_one_segment() -> None:
    assert notification_path("en", "openfda", "H-0015-2027") == "/en/n/openfda/H-0015-2027"


def test_keeps_the_dot_of_a_rasff_reference() -> None:
    assert notification_path("nl", "rasff", "2026.9489") == "/nl/n/rasff/2026.9489"


def test_spreads_an_nvwa_url_path_over_segments_without_the_leading_slash() -> None:
    key = "/actueel/nieuws/2026/10/24/veiligheidswaarschuwing-ah-pokebowl-sticky-tempeh-allergenen"
    assert notification_path("en", "nvwa", key) == (
        "/en/n/nvwa/actueel/nieuws/2026/10/24/"
        "veiligheidswaarschuwing-ah-pokebowl-sticky-tempeh-allergenen"
    )


def test_percent_encodes_characters_that_are_not_safe_in_a_segment() -> None:
    assert notification_path("en", "openfda", "A B/C") == "/en/n/openfda/A%20B%2FC"


def test_encodes_like_encode_uri_component() -> None:
    # encodeURIComponent leaves A-Z a-z 0-9 - _ . ! ~ * ' ( ) and encodes UTF-8 bytes.
    assert notification_path("en", "openfda", "a!~*'()é") == "/en/n/openfda/a!~*'()%C3%A9"
