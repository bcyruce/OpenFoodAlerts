"""Manage and unsubscribe links in Digest / Instant emails must match what the website
accepts (web/lib/subscriptions/links.ts); the literals are shared with its tests."""

from openfoodalerts.subscriptions.links import (
    list_unsubscribe_headers,
    manage_token,
    manage_url,
    unsubscribe_url,
)

SUBSCRIPTION_ID = "6f1c1f0e-3a8e-4c5a-9a53-2d1c3f6a7b8c"
# base64url(HMAC-SHA256("secret-1", "manage:v1:" + id)), computed with Node.js crypto.
# A public test vector, not a credential.
TOKEN = "wJMitkeX3x6Sd7td2o5oR6N2GOoZW6yZk2swTVSV3C8"  # gitleaks:allow
SITE = "https://openfoodalerts.nl"


def test_manage_token_matches_the_website() -> None:
    assert manage_token(SUBSCRIPTION_ID, "secret-1") == TOKEN
    assert manage_token(SUBSCRIPTION_ID, "secret-2") != TOKEN


def test_link_formats() -> None:
    assert manage_url(SITE, "nl", TOKEN) == f"{SITE}/nl/alerts/manage/{TOKEN}"
    assert unsubscribe_url(SITE, TOKEN) == f"{SITE}/api/unsubscribe?token={TOKEN}"
    # A trailing slash on the configured site URL does not double up.
    assert unsubscribe_url(SITE + "/", TOKEN) == f"{SITE}/api/unsubscribe?token={TOKEN}"


def test_rfc_8058_one_click_headers() -> None:
    assert list_unsubscribe_headers(SITE, TOKEN) == {
        "List-Unsubscribe": f"<{SITE}/api/unsubscribe?token={TOKEN}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
