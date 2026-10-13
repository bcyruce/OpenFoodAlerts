"""Manage and unsubscribe links for Digest and Instant emails (spec §10.5).

Must produce exactly what the website accepts; the TypeScript twin is
web/lib/subscriptions/links.ts and both test suites share the same literal values.

- manage token: base64url without padding of HMAC-SHA256(OFA_TOKEN_SECRET,
  "manage:v1:" + subscription id). The database stores only its SHA-256 (the website
  looks the Subscription up by that hash), so the mailer rebuilds it from the id.
- manage page: {SITE_URL}/{locale}/alerts/manage/{token}, locale = the Subscription's.
- one-click unsubscribe (RFC 8058): {SITE_URL}/api/unsubscribe?token={token}, sent as
  `List-Unsubscribe: <url>` plus `List-Unsubscribe-Post: List-Unsubscribe=One-Click`.
  Put the same URL in the body as the visible unsubscribe link: a GET on it never
  unsubscribes (mail scanners open links), it redirects to the manage page, whose
  button does.
"""

import base64
import hashlib
import hmac


def manage_token(subscription_id: str, token_secret: str) -> str:
    digest = hmac.new(
        token_secret.encode(), f"manage:v1:{subscription_id}".encode(), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _base(site_url: str) -> str:
    return site_url.rstrip("/")


def manage_url(site_url: str, locale: str, token: str) -> str:
    return f"{_base(site_url)}/{locale}/alerts/manage/{token}"


def unsubscribe_url(site_url: str, token: str) -> str:
    # base64url tokens need no percent-encoding.
    return f"{_base(site_url)}/api/unsubscribe?token={token}"


def list_unsubscribe_headers(site_url: str, token: str) -> dict[str, str]:
    """RFC 2369 / RFC 8058 headers for every Digest and Instant email (not for confirmations)."""
    return {
        "List-Unsubscribe": f"<{unsubscribe_url(site_url, token)}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
