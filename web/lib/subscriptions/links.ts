/**
 * Manage and unsubscribe links (spec §8, §10.5). A contract with the Python mailer
 * (pipeline/src/openfoodalerts/subscriptions/links.py), which must produce identical
 * links; both test suites share the same literal values.
 *
 * - token: the manage token, base64url(HMAC-SHA256(OFA_TOKEN_SECRET, "manage:v1:" + id))
 *   (crypto.ts). The website finds the Subscription by the token's SHA-256.
 * - manage page: {SITE_URL}/{locale}/alerts/manage/{token}
 * - one-click unsubscribe (RFC 8058): {SITE_URL}/api/unsubscribe?token={token}, in the
 *   headers `List-Unsubscribe: <url>` and `List-Unsubscribe-Post: List-Unsubscribe=One-Click`.
 *   A POST unsubscribes without cookies or JavaScript; a GET only redirects to the manage
 *   page (mail scanners open links), where a button unsubscribes.
 */
import { TOKEN_PATTERN } from "./crypto";

const base = (siteUrl: string) => siteUrl.replace(/\/+$/, "");

export function manageUrl(siteUrl: string, locale: string, token: string): string {
  return `${base(siteUrl)}/${locale}/alerts/manage/${token}`;
}

/** base64url tokens need no percent-encoding. */
export function unsubscribeUrl(siteUrl: string, token: string): string {
  return `${base(siteUrl)}/api/unsubscribe?token=${token}`;
}

/** For every Digest and Instant email (not for confirmation emails). */
export function listUnsubscribeHeaders(siteUrl: string, token: string): Record<string, string> {
  return {
    "List-Unsubscribe": `<${unsubscribeUrl(siteUrl, token)}>`,
    "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
  };
}

/** The token from a link or request, or null unless it has the token format. */
export function tokenFromLink(value: unknown): string | null {
  return typeof value === "string" && TOKEN_PATTERN.test(value) ? value : null;
}
