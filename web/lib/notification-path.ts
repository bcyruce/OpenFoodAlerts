/**
 * URLs of Notification detail pages: `/{locale}/n/{source}/{key…}`.
 *
 * - openFDA and RASFF keys (`H-0015-2027`, `2026.9489`) are one path segment.
 * - NVWA keys are URL paths (`/actueel/nieuws/2026/10/24/…`); they are spread over the
 *   remaining segments without their leading slash, so the page URL mirrors the NVWA URL.
 *
 * Each segment is percent-encoded. Use these helpers for every link to a detail page.
 */

export type SourceCode = "rasff" | "nvwa" | "openfda";

const PATH_KEYED: ReadonlySet<string> = new Set(["nvwa"]);

/** The unencoded `[...key]` route segments for a source_key. */
export function keySegments(source: string, key: string): string[] {
  return PATH_KEYED.has(source) ? key.replace(/^\/+/, "").split("/") : [key];
}

export function notificationPath(locale: string, source: string, key: string): string {
  return `/${locale}/n/${source}/${keySegments(source, key).map(encodeURIComponent).join("/")}`;
}

/** The source_key for a route's catch-all segments, or null if they cannot name one. */
export function keyFromSegments(source: string, segments: readonly string[]): string | null {
  if (segments.length === 0) return null;
  let decoded: string[];
  try {
    decoded = segments.map((s) => decodeURIComponent(s));
  } catch {
    return null;
  }
  if (PATH_KEYED.has(source)) return `/${decoded.join("/")}`;
  return decoded.length === 1 ? decoded[0] : null;
}

/**
 * Segments for `generateStaticParams`, or null when the key cannot be prerendered: Next.js
 * builds export paths from unencoded params, so a "/" inside one segment would split it.
 * Such pages still render on request through their percent-encoded URL.
 */
export function prerenderSegments(source: string, key: string): string[] | null {
  const segments = keySegments(source, key);
  return segments.some((s) => s === "" || s.includes("/")) ? null : segments;
}
