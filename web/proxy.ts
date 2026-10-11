import createMiddleware from "next-intl/middleware";
import { NextResponse, type NextRequest } from "next/server";
import { routing, SITE_LOCALES } from "./i18n/routing";

// Redirects paths without a locale prefix (e.g. `/`) to `/en` or `/nl` by Accept-Language.
// zh is left out of the negotiation because most pages do not exist in Chinese (spec §9);
// /zh/... paths are passed through untouched.
const negotiate = createMiddleware({ ...routing, locales: SITE_LOCALES, defaultLocale: "en" });

export default function proxy(request: NextRequest) {
  if (/^\/zh(\/|$)/.test(request.nextUrl.pathname)) return NextResponse.next();
  return negotiate(request);
}

export const config = {
  // Skip Next internals, API routes and files; `/n/...` is listed separately because
  // Notification keys may contain dots (RASFF `2026.9489`).
  matcher: ["/((?!api|_next|_vercel|.*\\..*).*)", "/n/:path*"],
};
