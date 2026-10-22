import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import Link from "next/link";
import { ZH_HOME, ZH_PAGES } from "@/content/zh";
import { ZH_MODULE_PAGES, ZH_WARNINGS_PAGE, type ZhModulePage } from "@/i18n/routing";
import { formatDate } from "@/lib/format";
import { isDraft, parseInline, type ZhBlock, type ZhPage } from "@/lib/zh-pages";
import { AdBox } from "./ad-box";

/**
 * Pages of the Chinese module (spec §9, ticket 32): `/zh` and the guide pages, zh only and
 * static. The text comes from `content/zh/*.ts`; this file only lays it out: title, review
 * date or the draft notice, sections, the official links, and the SnelVink ad box as the
 * last element (spec §11.3, UTM medium `zh_box`).
 */

type ZhT = Awaited<ReturnType<typeof getTranslations<"Zh">>>;

function metadata(path: string, page: ZhPage): Metadata {
  return {
    title: page.title,
    description: page.description,
    // zh only: no hreflang alternates.
    alternates: { canonical: path },
    // A draft is not written or reviewed by the owner yet: keep it out of search engines.
    ...(isDraft(page) ? { robots: { index: false, follow: true } } : {}),
  };
}

export function zhHomeMetadata(): Metadata {
  // The layout's title template does not apply to a page in the layout's own segment.
  return { ...metadata("/zh", ZH_HOME), title: { absolute: `${ZH_HOME.title} | OpenFoodAlerts` } };
}

export function zhGuideMetadata(slug: ZhModulePage): Metadata {
  return metadata(`/zh/${slug}`, ZH_PAGES[slug]);
}

/** A paragraph or list line with its `[text](url)` links. */
function Inline({ text }: { text: string }) {
  return parseInline(text).map((part, i) =>
    part.href === undefined ? (
      <span key={i}>{part.text}</span>
    ) : part.href.startsWith("/") ? (
      <Link key={i} href={part.href}>
        {part.text}
      </Link>
    ) : (
      <a key={i} href={part.href}>
        {part.text}
      </a>
    ),
  );
}

function Block({ block }: { block: ZhBlock }) {
  if (typeof block === "string") {
    return (
      <p className="mt-3 max-w-prose leading-7 text-slate-800">
        <Inline text={block} />
      </p>
    );
  }
  return (
    <ul className="mt-3 max-w-prose list-disc space-y-1 pl-5 leading-7 text-slate-800">
      {block.list.map((line, i) => (
        <li key={i}>
          <Inline text={line} />
        </li>
      ))}
    </ul>
  );
}

function PageHeader({ page, t }: { page: ZhPage; t: ZhT }) {
  return (
    <header>
      <h1 id="zh-title" className="text-3xl font-semibold text-slate-900">
        {page.title}
      </h1>
      {page.reviewedOn === null ? (
        <div
          role="note"
          aria-labelledby="zh-draft-title"
          data-testid="zh-draft-notice"
          className="mt-4 max-w-prose border-l-4 border-amber-600 bg-amber-50 p-4 text-slate-900"
        >
          <p id="zh-draft-title" className="font-semibold">
            {t("draftTitle")}
          </p>
          <p className="mt-1 text-sm">{t("draftBody")}</p>
        </div>
      ) : (
        <p className="mt-2 text-sm text-slate-700" data-testid="zh-reviewed-on">
          {t.rich("reviewedOn", {
            date: formatDate("zh", page.reviewedOn),
            time: (chunks) => <time dateTime={page.reviewedOn ?? undefined}>{chunks}</time>,
          })}
        </p>
      )}
      <p className="mt-4 max-w-prose leading-7 text-slate-800">{page.description}</p>
    </header>
  );
}

function Sections({ page, t }: { page: ZhPage; t: ZhT }) {
  return page.sections.map((section, i) => (
    <section key={section.heading} aria-labelledby={`zh-section-${i + 1}`} className="mt-8">
      <h2 id={`zh-section-${i + 1}`} className="text-xl font-semibold text-slate-900">
        {section.heading}
      </h2>
      {section.body.map((block, j) => (
        <Block key={j} block={block} />
      ))}
      {isDraft(page) && section.outline?.length ? (
        <div
          className="mt-3 max-w-prose rounded-md border border-dashed border-slate-400 p-3 text-sm text-slate-700"
          data-testid="zh-outline"
        >
          <p className="font-medium">{t("outlineLabel")}</p>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            {section.outline.map((line) => (
              <li key={line}>
                <Inline text={line} />
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  ));
}

function OfficialLinks({ page, t }: { page: ZhPage; t: ZhT }) {
  return (
    <section aria-labelledby="zh-official" className="mt-10" data-testid="zh-official-links">
      <h2 id="zh-official" className="text-xl font-semibold text-slate-900">
        {t("officialLinksHeading")}
      </h2>
      <p className="mt-2 text-slate-700">{t("officialLinksIntro")}</p>
      <ul className="mt-2 list-disc space-y-1 pl-5">
        {page.officialLinks.map((link) => (
          <li key={link.url}>
            <a href={link.url} hrefLang={link.lang}>
              {link.title}
            </a>{" "}
            <span className="text-sm text-slate-700">（{t(link.lang === "nl" ? "langNl" : "langEn")}）</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * Links between the guide pages and the warning stream (ticket 33); the current one is
 * marked.
 */
export async function ModuleNav({ current }: { current: ZhModulePage | typeof ZH_WARNINGS_PAGE }) {
  const [t, warnings] = await Promise.all([
    getTranslations({ locale: "zh", namespace: "Zh" }),
    getTranslations({ locale: "zh", namespace: "ZhWarnings" }),
  ]);
  const items = [
    ...ZH_MODULE_PAGES.map((slug) => ({ slug, label: ZH_PAGES[slug].navLabel })),
    { slug: ZH_WARNINGS_PAGE, label: warnings("navLabel") },
  ];
  return (
    <nav aria-label={t("moduleNavLabel")} data-testid="zh-module-nav" className="mb-6">
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
        {items.map(({ slug, label }) => (
          <li key={slug}>
            <Link
              href={`/zh/${slug}`}
              aria-current={slug === current ? "page" : undefined}
              className={slug === current ? "font-semibold" : undefined}
            >
              {label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

/** A guide page of the module, such as `/zh/nvwa-jiancha`. */
export async function ZhGuidePage({ slug }: { slug: ZhModulePage }) {
  const page = ZH_PAGES[slug];
  const t = await getTranslations({ locale: "zh", namespace: "Zh" });
  return (
    <>
      <ModuleNav current={slug} />
      <article aria-labelledby="zh-title">
        <PageHeader page={page} t={t} />
        <Sections page={page} t={t} />
        <OfficialLinks page={page} t={t} />
      </article>
      <AdBox locale="zh" />
    </>
  );
}

/** `/zh`: introduction, the guide pages and the Chinese subscription flow. */
export async function ZhHome() {
  const [t, warnings] = await Promise.all([
    getTranslations({ locale: "zh", namespace: "Zh" }),
    getTranslations({ locale: "zh", namespace: "ZhWarnings" }),
  ]);
  return (
    <>
      <article aria-labelledby="zh-title">
        <PageHeader page={ZH_HOME} t={t} />
        <Sections page={ZH_HOME} t={t} />
        <section aria-labelledby="zh-guide" className="mt-10" data-testid="zh-guide-pages">
          <h2 id="zh-guide" className="text-xl font-semibold text-slate-900">
            {t("pagesHeading")}
          </h2>
          <ul className="mt-4 grid gap-4 md:grid-cols-2">
            {ZH_MODULE_PAGES.map((slug) => {
              const page = ZH_PAGES[slug];
              return (
                <li key={slug} className="rounded-lg border border-slate-300 p-4">
                  <h3 className="font-semibold">
                    <Link href={`/zh/${slug}`}>{page.title}</Link>
                  </h3>
                  <p className="mt-1 text-sm leading-6 text-slate-700">{page.description}</p>
                  <p className="mt-2 text-xs text-slate-700">
                    {page.reviewedOn === null
                      ? t("pageDraft")
                      : t("pageReviewed", { date: formatDate("zh", page.reviewedOn) })}
                  </p>
                </li>
              );
            })}
          </ul>
        </section>
        {/* Ticket 33: the warning stream is AI text, not a reviewed guide page. */}
        <section aria-labelledby="zh-warnings-card" className="mt-10" data-testid="zh-warnings-card">
          <div className="rounded-lg border-2 border-dashed border-violet-400 bg-violet-50 p-4">
            <h2 id="zh-warnings-card" className="text-xl font-semibold text-slate-900">
              <Link href={`/zh/${ZH_WARNINGS_PAGE}`}>{warnings("title")}</Link>
            </h2>
            <p className="mt-1 max-w-prose text-sm leading-6 text-slate-800">{warnings("cardBody")}</p>
            <p className="mt-2 text-xs text-slate-800">{warnings("cardNote")}</p>
          </div>
        </section>
        <section aria-labelledby="zh-subscribe" className="mt-10" data-testid="zh-subscribe">
          <h2 id="zh-subscribe" className="text-xl font-semibold text-slate-900">
            {t("subscribeHeading")}
          </h2>
          <p className="mt-2 max-w-prose leading-7 text-slate-700">{t("subscribeBody")}</p>
          <p className="mt-3">
            <Link href="/zh/alerts" className="font-medium">
              {t("subscribeLink")}
            </Link>
          </p>
        </section>
        <OfficialLinks page={ZH_HOME} t={t} />
      </article>
      <AdBox locale="zh" />
    </>
  );
}
