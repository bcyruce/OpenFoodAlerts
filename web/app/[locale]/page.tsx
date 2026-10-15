import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { cacheLife, cacheTag } from "next/cache";
import Link from "next/link";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";
import { AdBox } from "@/components/ad-box";
import { SOURCE_COLORS } from "@/components/dashboard/options";
import { TimeSeriesThumbnail, TopThumbnail } from "@/components/home-charts";
import { ZhHome, zhHomeMetadata } from "@/components/zh-page";
import { isSiteLocale, SITE_LOCALES } from "@/i18n/routing";
import { getDb } from "@/lib/db";
import { NO_FILTERS } from "@/lib/filters";
import { formatDate } from "@/lib/format";
import { getRecentNotifications, type RecentSource } from "@/lib/home";
import { getStats } from "@/lib/stats";
import { formatMonth, timeSeriesTable } from "@/lib/stats-tables";

// ISR (spec §9): the whole page is static and regenerated in the background at most once
// an hour (cacheLife "hours": revalidate 1 h), "last 7 days" included.
const TOP_HAZARDS = 5;

async function loadHome(locale: "en" | "nl") {
  "use cache";
  cacheLife("hours");
  cacheTag("home");
  const db = getDb();
  const [recent, stats] = await Promise.all([
    getRecentNotifications(db, { locale }),
    getStats(db, { filters: NO_FILTERS, months: 12 }, { locale }),
  ]);
  return { recent, stats };
}

export async function generateMetadata({ params }: PageProps<"/[locale]">): Promise<Metadata> {
  const { locale } = await params;
  if (locale === "zh") return zhHomeMetadata();
  if (!isSiteLocale(locale)) return {};
  const t = await getTranslations({ locale, namespace: "Home" });
  return {
    title: { absolute: "OpenFoodAlerts" },
    description: t("metaDescription"),
    alternates: {
      canonical: `/${locale}`,
      languages: Object.fromEntries(SITE_LOCALES.map((l) => [l, `/${l}`])),
    },
  };
}

// zh: the landing page of the Chinese module (ticket 32), static, no data.
export default async function Home({ params }: PageProps<"/[locale]">) {
  const { locale } = await params;
  if (locale === "zh") return <ZhHome />;
  if (!isSiteLocale(locale)) notFound();
  const [{ recent, stats }, t] = await Promise.all([
    loadHome(locale),
    getTranslations({ locale, namespace: "Home" }),
  ]);
  const number = new Intl.NumberFormat(locale);
  const table = timeSeriesTable(stats);
  const rasff = stats.sources.find((s) => s.source === "rasff");
  const topHazards = rasff?.top.hazard.slice(0, TOP_HAZARDS) ?? [];
  return (
    <>
      <section aria-labelledby="home-heading">
        <h1 id="home-heading" className="text-3xl font-semibold text-slate-900">
          {t("heading")}
        </h1>
        <p className="mt-3 max-w-prose text-slate-700">{t("intro")}</p>
        <h2 className="sr-only">{t("pointsHeading")}</h2>
        <ul className="mt-4 max-w-prose list-disc space-y-1 pl-5 text-slate-700">
          <li>{t("pointArchive")}</li>
          <li>{t("pointSources")}</li>
          <li>{t("pointAi")}</li>
        </ul>
      </section>

      <section aria-labelledby="recent-heading" className="mt-10" data-testid="home-recent">
        <h2 id="recent-heading" className="text-xl font-semibold">
          {t("recentHeading")}
        </h2>
        <p className="mt-1 text-sm text-slate-700">
          {t("recentIntro", {
            from: formatDate(locale, recent.from),
            to: formatDate(locale, recent.to),
          })}
        </p>
        <div className="mt-4 grid gap-4 md:grid-cols-3">
          {recent.sources.map((s) => (
            <RecentBlock key={s.source} locale={locale} source={s} t={t} />
          ))}
        </div>
      </section>

      <section aria-labelledby="charts-heading" className="mt-10" data-testid="home-charts">
        <h2 id="charts-heading" className="text-xl font-semibold">
          {t("chartsHeading")}
        </h2>
        <p className="mt-1 text-sm text-slate-700">{t("chartsIntro")}</p>
        <div className="mt-4 grid gap-6 md:grid-cols-2">
          <div>
            <h3 className="font-semibold">{t("timeSeriesHeading")}</h3>
            <TimeSeriesThumbnail stats={stats} locale={locale} label={t("timeSeriesLabel")} />
            <DataTable summary={t("showTable")} caption={t("timeSeriesHeading")} testId="home-table-timeseries">
              <thead>
                <tr>
                  <th scope="col">{t("month")}</th>
                  {table.columns.map((c) => (
                    <th key={c} scope="col" className="text-right">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {table.rows.map((r) => (
                  <tr key={r.month}>
                    <th scope="row">{formatMonth(locale, r.month)}</th>
                    {r.counts.map((c, i) => (
                      <td key={table.columns[i]} className="text-right">
                        {number.format(c)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th scope="row">{t("total")}</th>
                  {table.totals.map((c, i) => (
                    <td key={table.columns[i]} className="text-right font-semibold">
                      {number.format(c)}
                    </td>
                  ))}
                </tr>
              </tfoot>
            </DataTable>
          </div>
          <div>
            <h3 className="font-semibold">{t("topHazardsHeading", { source: "RASFF" })}</h3>
            {topHazards.length === 0 ? (
              <p className="mt-2 text-sm text-slate-700">{t("topHazardsEmpty")}</p>
            ) : (
              <>
                <TopThumbnail
                  items={topHazards}
                  color={SOURCE_COLORS.rasff}
                  locale={locale}
                  label={t("topHazardsLabel", { source: "RASFF" })}
                />
                <DataTable
                  summary={t("showTable")}
                  caption={t("topHazardsHeading", { source: "RASFF" })}
                  testId="home-table-top"
                >
                  <thead>
                    <tr>
                      <th scope="col">{t("category")}</th>
                      <th scope="col" className="text-right">
                        {t("count")}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {topHazards.map((item) => (
                      <tr key={item.value}>
                        <th scope="row">{item.label}</th>
                        <td className="text-right">{number.format(item.count)}</td>
                      </tr>
                    ))}
                  </tbody>
                </DataTable>
              </>
            )}
          </div>
        </div>
        <p className="mt-4">
          <Link href={`/${locale}/dashboard`}>{t("dashboardLink")}</Link>
        </p>
      </section>

      <section aria-labelledby="subscribe-heading" className="mt-10" data-testid="home-subscribe">
        <h2 id="subscribe-heading" className="text-xl font-semibold">
          {t("subscribeHeading")}
        </h2>
        <p className="mt-1 max-w-prose text-slate-700">{t("subscribeBody")}</p>
        <p className="mt-3">
          <Link href={`/${locale}/alerts`} className="font-medium">
            {t("subscribe")}
          </Link>
        </p>
      </section>

      <AdBox locale={locale} />
    </>
  );
}

type HomeT = Awaited<ReturnType<typeof getTranslations<"Home">>>;

function RecentBlock({ locale, source: s, t }: { locale: string; source: RecentSource; t: HomeT }) {
  return (
    <section
      aria-labelledby={`recent-${s.source}`}
      className="rounded-lg border border-slate-300 p-4"
      data-testid={`recent-${s.source}`}
    >
      <h3 id={`recent-${s.source}`} className="flex items-center gap-2 font-semibold">
        <span
          aria-hidden="true"
          className="inline-block h-3 w-3 rounded-sm"
          style={{ background: SOURCE_COLORS[s.source] }}
        />
        {s.label}
      </h3>
      <p className="mt-1 text-sm text-slate-700">{t("recentCount", { count: s.total })}</p>
      {s.items.length === 0 ? (
        <p className="mt-2 text-sm text-slate-700">{t("recentNone")}</p>
      ) : (
        <>
          <ol className="mt-2 space-y-3">
            {s.items.map((item) => (
              <li key={item.sourceKey} className="text-sm" data-testid="recent-item">
                <a href={item.path} className="font-medium">
                  {item.title}
                </a>
                <p className="text-slate-700">
                  <time dateTime={item.publishedAt}>{formatDate(locale, item.publishedAt)}</time> ·{" "}
                  {item.notificationType}
                </p>
              </li>
            ))}
          </ol>
          <p className="mt-3 text-sm">
            <a href={s.searchPath}>{t("recentMore", { count: s.total, source: s.label })}</a>
          </p>
        </>
      )}
    </section>
  );
}

function DataTable({
  summary,
  caption,
  testId,
  children,
}: {
  summary: string;
  caption: string;
  testId: string;
  children: ReactNode;
}) {
  return (
    <details className="mt-2" data-testid={testId}>
      <summary className="cursor-pointer text-sm font-medium text-blue-800">{summary}</summary>
      <div className="mt-2 overflow-x-auto" tabIndex={0} role="region" aria-label={`${summary}: ${caption}`}>
        <table className="w-full text-sm tabular-nums [&_td]:border-b [&_td]:border-slate-200 [&_td]:px-2 [&_td]:py-1 [&_th]:border-b [&_th]:border-slate-200 [&_th]:px-2 [&_th]:py-1 [&_th:not(.text-right)]:text-left [&_th]:font-medium">
          <caption className="sr-only">{caption}</caption>
          {children}
        </table>
      </div>
    </details>
  );
}
