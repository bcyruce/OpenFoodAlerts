/**
 * POST /api/delete (spec §8, §11.1 #5), JSON {"token": …}: "delete my data". Deletes every
 * Subscription of the address with its email deliveries and keeps only the address's
 * HMAC on the do-not-send list. 200 {"status":"deleted"} | 400 invalid | 404 not_found |
 * 415 | 429. JSON only, so it cannot be triggered by a plain link or form.
 */
import { isJson, jsonBody, rateLimited, reply } from "@/lib/subscriptions/http";
import { tokenFromLink } from "@/lib/subscriptions/links";
import { deleteSubscriptionData } from "@/lib/subscriptions/manage";
import { logEvent, manageDeps, manageLimiter } from "@/lib/subscriptions/runtime";

export async function POST(request: Request) {
  if (!isJson(request)) return reply(415, { error: "unsupported_media_type" });
  const limited = rateLimited(request, manageLimiter);
  if (limited) return limited;
  const token = tokenFromLink((await jsonBody(request))?.token);
  if (!token) return reply(400, { error: "invalid" });

  const outcome = await deleteSubscriptionData(manageDeps(), token);
  logEvent("subscription_deleted", { outcome });
  if (outcome === "invalid") return reply(404, { error: "not_found" });
  return reply(200, { status: "deleted" });
}
