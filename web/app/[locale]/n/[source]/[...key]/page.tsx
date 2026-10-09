import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { cacheLife, cacheTag } from "next/cache";
import { notFound } from "next/navigation";
import { NotificationDetailView } from "@/components/notification-detail";
import { routing } from "@/i18n/routing";
import { getDb } from "@/lib/db";
import { keyFromSegments, keySegments, notificationPath } from "@/lib/notification-path";
import {
  getNotificationDetail,
  listRecentNotificationKeys,
  type NotificationDetail,
} from "@/lib/notifications";
import { OG_LOCALES, reportErrorUrl, SITE_URL } from "@/lib/site";

// ISR: the complete page is static; unlisted keys render on first request (blocking, so a
// missing or non-food Notification gets a real 404) and are then served from the cache.
export const ensureStatic = "navigation";
// The page reads its params outside <Suspense> on purpose (no fallback shell to stream),
// so navigations into it block until the static page is ready.
export const instant = false;

const PRERENDERED = 50;

export async function generateStaticParams(): Promise<{ source: string; key: string[] }[]> {
  const recent = await listRecentNotificationKeys(getDb(), PRERENDERED);
  const params = recent.map(({ source, key }) => ({ source, key: keySegments(source, key) }));
  // ensureStatic needs at least one parameter set, even on an empty database.
  return params.length > 0 ? params : [{ source: "openfda", key: ["none"] }];
}

/** Cached per Notification; the pipeline's changes appear within the revalidate window. */
async function loadNotification(source: string, key: string): Promise<NotificationDetail | null> {
  "use cache";
  cacheLife("hours");
  cacheTag(`notification:${source}:${key}`);
  return getNotificationDetail(getDb(), source, key);
}

async function resolve(params: PageProps<"/[locale]/n/[source]/[...key]">["params"]) {
  const { locale, source, key: segments } = await params;
  const key = keyFromSegments(source, segments);
  const notification = key === null ? null : await loadNotification(source, key);
  return { locale, notification };
}

function truncate(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 1).trimEnd()}…`;
}

export async function generateMetadata({
  params,
}: PageProps<"/[locale]/n/[source]/[...key]">): Promise<Metadata> {
  const { locale, notification: n } = await resolve(params);
  if (!n) return {};
  const t = await getTranslations({ locale, namespace: "Notification" });
  const path = notificationPath(locale, n.source.code, n.sourceKey);
  const title = `${n.title} (${n.sourceKey})`;
  const description = truncate(
    [n.hazardText, n.productText].filter(Boolean).join(" — ") ||
      t("metaDescriptionFallback", { source: n.source.name }),
    200,
  );
  return {
    title,
    description,
    alternates: {
      canonical: path,
      languages: Object.fromEntries(
        routing.locales.map((l) => [l, notificationPath(l, n.source.code, n.sourceKey)]),
      ),
    },
    openGraph: {
      type: "article",
      title,
      description,
      url: path,
      siteName: "OpenFoodAlerts",
      locale: OG_LOCALES[locale],
      alternateLocale: routing.locales.filter((l) => l !== locale).map((l) => OG_LOCALES[l]),
      publishedTime: n.publishedAt ?? n.firstSeenAt,
      modifiedTime: n.lastChangedAt,
    },
  };
}

export default async function NotificationPage({
  params,
}: PageProps<"/[locale]/n/[source]/[...key]">) {
  const { locale, notification } = await resolve(params);
  if (!notification) notFound();
  const pageUrl = `${SITE_URL}${notificationPath(locale, notification.source.code, notification.sourceKey)}`;
  return (
    <NotificationDetailView
      locale={locale}
      notification={notification}
      reportErrorHref={reportErrorUrl(
        pageUrl,
        `${notification.source.name} ${notification.sourceKey}`,
      )}
    />
  );
}
