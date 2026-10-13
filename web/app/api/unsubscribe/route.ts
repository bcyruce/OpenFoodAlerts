/**
 * /api/unsubscribe (spec §8, §10.5): stop all email to a Subscription at once.
 *
 * - POST ?token=… with the form body `List-Unsubscribe=One-Click` (RFC 8058, sent by mail
 *   clients from the `List-Unsubscribe` header): needs no cookies, JavaScript or session.
 * - POST JSON {"token": …} (the button on the manage page).
 *   Both answer 200 {"status":"unsubscribed"} (also when it already was) | 400 invalid |
 *   404 not_found. Not rate limited: one-click requests come from a few mail-provider
 *   addresses on behalf of many subscribers, and the operation is idempotent.
 * - GET ?token=… never unsubscribes (mail scanners open links): 303 to the manage page,
 *   whose unsubscribe button does it.
 *
 * The token is the authority, so a cross-site form post cannot do anything its sender
 * could not do directly; no CSRF protection is needed or wanted (RFC 8058 §3.2).
 */
import type { NextRequest } from "next/server";
import { isJson, jsonBody, PRIVATE_HEADERS, rateLimited, reply } from "@/lib/subscriptions/http";
import { tokenFromLink } from "@/lib/subscriptions/links";
import { findSubscription, unsubscribe } from "@/lib/subscriptions/manage";
import { logEvent, manageDeps, manageLimiter } from "@/lib/subscriptions/runtime";

const ONE_CLICK = "One-Click";

/** RFC 8058 body, multipart or urlencoded (also when a client leaves out the content type). */
async function oneClick(request: NextRequest): Promise<boolean> {
  try {
    const type = request.headers.get("content-type")?.toLowerCase() ?? "";
    if (type.startsWith("multipart/form-data")) {
      return (await request.formData()).get("List-Unsubscribe") === ONE_CLICK;
    }
    return new URLSearchParams(await request.text()).get("List-Unsubscribe") === ONE_CLICK;
  } catch {
    return false;
  }
}

export async function POST(request: NextRequest) {
  let token: string | null;
  let via: "one_click" | "page";
  if (isJson(request)) {
    token = tokenFromLink((await jsonBody(request))?.token);
    via = "page";
  } else {
    if (!(await oneClick(request))) return reply(400, { error: "invalid" });
    token = tokenFromLink(request.nextUrl.searchParams.get("token"));
    via = "one_click";
  }
  if (!token) return reply(400, { error: "invalid" });

  const outcome = await unsubscribe(manageDeps(), token);
  logEvent("subscription_unsubscribed", { outcome, via });
  if (outcome === "invalid") return reply(404, { error: "not_found" });
  return reply(200, { status: "unsubscribed" });
}

export async function GET(request: NextRequest) {
  const limited = rateLimited(request, manageLimiter);
  if (limited) return limited;
  const token = tokenFromLink(request.nextUrl.searchParams.get("token"));
  const subscription = token ? await findSubscription(manageDeps().db, token) : null;
  const locale = subscription?.locale ?? "en";
  // Relative Location: correct behind any proxy, whatever host the request came in on.
  const location = token ? `/${locale}/alerts/manage/${token}#unsubscribe` : `/${locale}/alerts/manage/invalid`;
  return new Response(null, { status: 303, headers: { ...PRIVATE_HEADERS, location } });
}
