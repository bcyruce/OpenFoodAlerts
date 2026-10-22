import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { cacheLife, cacheTag } from "next/cache";
import Link from "next/link";
import { getDb } from "@/lib/db";
import { formatDate } from "@/lib/format";
import { getZhWarnings, zhWarningsPath, type ZhWarning, type ZhWarningsPage } from "@/lib/zh-warnings";
import { AdBox } from "./ad-box";
import { AiBadge } from "./ai-badge";
import { aiBadgeWriter } from "./ai-badge-text";
import { ModuleNav } from "./zh-page";

/**
 * `/zh/jinggao` (spec §9, ticket 33): NVWA food warnings with their Chinese AI summary, the
 * Dutch title, the date, "未分级" (ADR 0006), the official link and the English detail
 * page. ISR: the data is cached for an hour (cacheLife "hours"), so the page is static
 * and regenerated in the background.
 */

type T = Awaited<ReturnType<typeof getTranslations<"ZhWarnings">>>;

/** One page of the stream, or null past the last page; cached for an hour. */
export async function loadZhWarnings(page: number): Promise<ZhWarningsPage | null> {
  "use cache";
  cacheLife("hours");
  cacheTag("zh-warnings");
  return getZhWarnings(getDb(), { page });
}

export async function zhWarningsMetadata(page: number): Promise<Metadata> {
  const t = await getTranslations({ locale: "zh", namespace: "ZhWarnings" });
  return {
    title: page === 1 ? t("title") : t("pageTitle", { page }),
    description: t("metaDescription"),
    // zh only: no hreflang alternates. Each page is its own canonical URL.
    alternates: { canonical: zhWarningsPath(page) },
  };
}

function Warning({
  warning: w,
  t,
  badge,
}: {
  warning: ZhWarning;
  t: T;
  badge: Awaited<ReturnType<typeof aiBadgeWriter>>;
}) {
  const heading = `zh-warning-${w.id}`;
  return (
    <li data-testid="zh-warning" className="border-b border-slate-200 pb-6">
      <article aria-labelledby={heading}>
        <h2 id={heading} lang="nl" className="break-words text-lg font-semibold text-slate-900">
          {w.title}
        </h2>
        <p className="mt-1 text-sm text-slate-700">
          {w.publishedAt && (
            <>
              {t("published")}：<time dateTime={w.publishedAt}>{formatDate("zh", w.publishedAt)}</time>
              {" · "}
            </>
          )}
          {t("severity")}：<span data-testid="zh-warning-severity">{t("notGraded")}</span>
          {w.withdrawn && (
            <>
              {" · "}
              <strong className="font-semibold text-slate-900">{t("withdrawn")}</strong>
            </>
          )}
        </p>
        {w.summary ? (
          <div
            data-testid="zh-warning-summary"
            className="mt-3 rounded-md border-2 border-dashed border-violet-400 bg-violet-50 p-3"
          >
            <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-violet-950">
              <AiBadge {...badge(w.summary, w.sourceUrl)} />
              <span>{t("summaryLabel")}</span>
            </p>
            <p className="mt-1 leading-7 text-slate-900">{w.summary.text}</p>
          </div>
        ) : (
          <p data-testid="zh-warning-no-summary" className="mt-3 text-slate-700">
            {t("noSummary")}。{t("noSummaryNote")}
          </p>
        )}
        <p className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm">
          <a href={w.sourceUrl} hrefLang="nl" rel="external noopener" data-testid="zh-warning-official">
            {t("officialLink")}（{t("langNl")}）
          </a>
          <a href={w.detailPath} hrefLang="en" data-testid="zh-warning-detail">
            {t("detailLink")}（{t("langEn")}）
          </a>
        </p>
      </article>
    </li>
  );
}

function Pagination({ data, t }: { data: ZhWarningsPage; t: T }) {
  if (data.totalPages <= 1) return null;
  return (
    <nav aria-label={t("paginationLabel")} data-testid="zh-warnings-pagination" className="mt-8">
      <ul className="flex flex-wrap items-center gap-x-6 gap-y-2">
        {data.page > 1 && (
          <li>
            <Link href={zhWarningsPath(data.page - 1)} rel="prev">
              {t("previous")}
            </Link>
          </li>
        )}
        <li className="text-sm text-slate-700">
          {t("pageInfo", { page: data.page, pages: data.totalPages, total: data.total })}
        </li>
        {data.page < data.totalPages && (
          <li>
            <Link href={zhWarningsPath(data.page + 1)} rel="next">
              {t("next")}
            </Link>
          </li>
        )}
      </ul>
    </nav>
  );
}

/** A page of the stream; `data` from `loadZhWarnings`. */
export async function ZhWarningsView({ data }: { data: ZhWarningsPage }) {
  const [t, badge] = await Promise.all([
    getTranslations({ locale: "zh", namespace: "ZhWarnings" }),
    aiBadgeWriter("zh"),
  ]);
  return (
    <>
      <ModuleNav current="jinggao" />
      <section aria-labelledby="zh-warnings-title">
        <h1 id="zh-warnings-title" className="text-3xl font-semibold text-slate-900">
          {t("title")}
        </h1>
        <p className="mt-4 max-w-prose leading-7 text-slate-800">{t("intro")}</p>
        <p className="mt-2 max-w-prose leading-7 text-slate-800">{t("notGradedNote")}</p>
        <p className="mt-2 text-sm text-slate-700">
          {t("updated")} {t("pageInfo", { page: data.page, pages: data.totalPages, total: data.total })}
        </p>
        {data.items.length === 0 ? (
          <p className="mt-8 text-slate-800">{t("empty")}</p>
        ) : (
          <ol className="mt-8 space-y-6" data-testid="zh-warnings">
            {data.items.map((w) => (
              <Warning key={w.id} warning={w} t={t} badge={badge} />
            ))}
          </ol>
        )}
        <Pagination data={data} t={t} />
      </section>
      <AdBox locale="zh" />
    </>
  );
}
