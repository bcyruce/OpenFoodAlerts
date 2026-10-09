import createMiddleware from "next-intl/middleware";
import { routing } from "./i18n/routing";

// Redirects paths without a locale prefix (e.g. `/`) to `/en` or `/nl` by Accept-Language.
export default createMiddleware(routing);

export const config = {
  // Skip Next internals, API routes and files; `/n/...` is listed separately because
  // Notification keys may contain dots (RASFF `2026.9489`).
  matcher: ["/((?!api|_next|_vercel|.*\\..*).*)", "/n/:path*"],
};
