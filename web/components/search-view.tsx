import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";
import type { FilterFacet } from "@/lib/filter-sql";
import { toSearchParams, type SearchQuery } from "@/lib/filters";
import { formatDate } from "@/lib/format";
import {
  SOURCE_LABELS,
  type ClassifiedValue,
  type FacetValue,
  type SearchResponse,
  type SearchResult,
} from "@/lib/search";

type Props = { locale: string; query: SearchQuery; response: SearchResponse };

/** URL parameter of each facet, in the canonical order of `toSearchParams`. */
const FACET_PARAMS: [FilterFacet, string][] = [
  ["source", "source"],
  ["hazard", "hazard"],
  ["product", "product"],
  ["country", "country"],
  ["risk", "risk"],
];

/** Facets that are short enough to show expanded. */
const OPEN_FACETS: ReadonlySet<FilterFacet> = new Set(["source", "risk"]);

type T = Awaited<ReturnType<typeof getTranslations<"Search">>>;

/**
 * The search form (a plain GET form, so it works without JavaScript and every state is a
 * shareable URL), the results and the pagination.
 */
export async function SearchView({ locale, query, response }: Props) {
  const t = await getTranslations({ locale, namespace: "Search" });
  const tAll = await getTranslations({ locale });
  const action = `/${locale}/search`;
  const f = query.filters;
  const pageHref = (page: number) => {
    const params = toSearchParams({ ...query, page });
    return params.size > 0 ? `${action}?${params}` : action;
  };
  const productType = (value: string) =>
    tAll.has(`ProductTypes.${value}`) ? tAll(`ProductTypes.${value}`) : value;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-semibold text-slate-900">{t("title")}</h1>
        <p className="mt-2 text-slate-700">{t("intro")}</p>
      </header>

      <form action={action} method="get" className="lg:grid lg:grid-cols-[17rem_1fr] lg:gap-8">
        <div role="search" className="lg:col-span-2">
          <label htmlFor="search-q" className="block font-medium text-slate-900">
            {t("queryLabel")}
          </label>
          <div className="mt-1 flex gap-2">
            <input
              id="search-q"
              type="search"
              name="q"
              defaultValue={query.q}
              maxLength={200}
              aria-describedby="search-q-hint"
              className="w-full rounded border border-slate-500 px-3 py-2 text-slate-900"
            />
            <button
              type="submit"
              className="rounded bg-blue-700 px-4 py-2 font-medium text-white hover:bg-blue-800"
            >
              {t("submit")}
            </button>
          </div>
          <p id="search-q-hint" className="mt-1 text-sm text-slate-700">
            {t("queryHint")}
          </p>
        </div>

        <section aria-labelledby="filters-heading" className="mt-6 lg:mt-2">
          <h2 id="filters-heading" className="text-xl font-semibold">
            {t("filtersHeading")}
          </h2>
          {FACET_PARAMS.map(([facet, param]) => (
            <Facet
              key={facet}
              title={t(`facet.${facet}`)}
              param={param}
              values={response.facets[facet]}
              open={OPEN_FACETS.has(facet) || response.facets[facet].some((v) => v.selected)}
              empty={t("facetEmpty")}
            />
          ))}
          <fieldset className="border-t border-slate-200 py-3">
            <legend className="float-left w-full font-medium">{t("dateHeading")}</legend>
            <div className="clear-both grid grid-cols-2 gap-2 pt-2 text-sm">
              <label>
                <span className="block text-slate-700">{t("from")}</span>
                <input
                  type="date"
                  name="from"
                  defaultValue={f.from ?? ""}
                  className="w-full rounded border border-slate-500 px-1 py-1"
                />
              </label>
              <label>
                <span className="block text-slate-700">{t("to")}</span>
                <input
                  type="date"
                  name="to"
                  defaultValue={f.to ?? ""}
                  className="w-full rounded border border-slate-500 px-1 py-1"
                />
              </label>
            </div>
          </fieldset>
          <div className="border-t border-slate-200 py-3">
            <label className="flex items-start gap-2 font-medium">
              <input
                type="checkbox"
                name="official_only"
                value="1"
                defaultChecked={f.officialOnly}
                aria-describedby="official-only-hint"
                className="mt-1"
              />
              {t("officialOnly")}
            </label>
            <p id="official-only-hint" className="mt-1 text-sm text-slate-700">
              {t("officialOnlyHint")}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-4 border-t border-slate-200 pt-3">
            <button
              type="submit"
              className="rounded bg-blue-700 px-4 py-2 font-medium text-white hover:bg-blue-800"
            >
              {t("apply")}
            </button>
            <a href={query.q ? `${action}?${new URLSearchParams({ q: query.q })}` : action}>
              {t("clear")}
            </a>
          </div>
        </section>

        <section aria-labelledby="results-heading" className="mt-8 lg:mt-2">
          <h2 id="results-heading" className="text-xl font-semibold">
            {t("resultsHeading")}
          </h2>
          <p className="mt-1 text-slate-700" data-testid="result-count">
            {t("resultCount", { count: response.total })}
          </p>
          {response.total === 0 && <p className="mt-2 text-slate-700">{t("noResults")}</p>}
          <ol className="mt-4 space-y-4" data-testid="results">
            {response.results.map((r) => (
              <ResultItem
                key={`${r.source}:${r.sourceKey}`}
                locale={locale}
                result={r}
                t={t}
                productType={productType(r.productType)}
              />
            ))}
          </ol>
          {response.pageCount > 1 && (
            <nav aria-label={t("pagination")} className="mt-6 flex items-center gap-4">
              {response.page > 1 && (
                <a href={pageHref(response.page - 1)} rel="prev">
                  {t("previous")}
                </a>
              )}
              <span aria-current="page">
                {t("pageOf", { page: response.page, pageCount: response.pageCount })}
              </span>
              {response.page < response.pageCount && (
                <a href={pageHref(response.page + 1)} rel="next">
                  {t("next")}
                </a>
              )}
            </nav>
          )}
        </section>
      </form>
    </div>
  );
}

function Facet({
  title,
  param,
  values,
  open,
  empty,
}: {
  title: string;
  param: string;
  values: FacetValue[];
  open: boolean;
  empty: string;
}) {
  const selected = values.filter((v) => v.selected).length;
  return (
    <details
      open={open}
      data-testid={`facet-${param}`}
      className="border-t border-slate-200 py-3 first-of-type:border-t-0"
    >
      <summary className="cursor-pointer font-medium">
        {title}
        {selected > 0 && <span className="font-normal text-slate-700"> ({selected})</span>}
      </summary>
      <fieldset className="mt-2">
        <legend className="sr-only">{title}</legend>
        {values.length === 0 ? (
          <p className="text-sm text-slate-700">{empty}</p>
        ) : (
          <ul className="max-h-64 space-y-1 overflow-y-auto pr-1 text-sm">
            {values.map((v) => (
              <li key={v.value}>
                <label className="flex items-start gap-2">
                  <input
                    type="checkbox"
                    name={param}
                    value={v.value}
                    defaultChecked={v.selected}
                    className="mt-0.5"
                  />
                  <span>
                    {v.label} <span className="text-slate-700">({v.count})</span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}
      </fieldset>
    </details>
  );
}

function truncate(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 1).trimEnd()}…`;
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="sm:grid sm:grid-cols-[10rem_1fr] sm:gap-3">
      <dt className="font-medium text-slate-700">{label}</dt>
      <dd className="break-words text-slate-900">{children}</dd>
    </div>
  );
}

/** Official values plainly, AI classifications badged and dashed (spec §9). */
function Values({ values, t }: { values: ClassifiedValue[]; t: T }) {
  return (
    <ul className="flex flex-wrap gap-1.5">
      {values.map((v) => (
        <li key={`${v.provenance}:${v.value}`}>
          {v.provenance === "ai" ? (
            <span
              data-provenance="ai"
              className="inline-flex items-center gap-1 rounded border border-dashed border-violet-500 bg-violet-50 px-1.5 text-violet-950"
            >
              <span aria-hidden="true" className="rounded bg-violet-800 px-1 text-xs font-semibold text-white">
                {t("aiBadge")}
              </span>
              {v.label}
              <span className="sr-only"> ({t("aiValue")})</span>
            </span>
          ) : (
            <span
              data-provenance="official"
              className="inline-block rounded border border-slate-300 bg-slate-50 px-1.5"
            >
              {v.label}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

function ResultItem({
  locale,
  result: r,
  t,
  productType,
}: {
  locale: string;
  result: SearchResult;
  t: T;
  productType: string;
}) {
  const id = `result-${r.source}-${r.sourceKey.replace(/[^A-Za-z0-9-]/g, "-")}`;
  return (
    <li>
      <article
        aria-labelledby={id}
        className="rounded-lg border border-slate-300 p-4"
        data-testid="result"
        data-source={r.source}
      >
        <p className="text-sm font-medium text-slate-700">
          {SOURCE_LABELS[r.source] ?? r.source} · {r.notificationType}
          {r.source !== "nvwa" && (
            <>
              {" "}
              · <span className="font-mono">{r.sourceKey}</span>
            </>
          )}
        </p>
        <h3 id={id} className="mt-1 text-lg font-semibold">
          <a href={r.path}>{r.title}</a>
        </h3>
        <dl className="mt-2 space-y-1 text-sm">
          <Field label={t("published")}>
            {r.publishedAt ? (
              <time dateTime={r.publishedAt}>{formatDate(locale, r.publishedAt)}</time>
            ) : (
              t("notPublished")
            )}
          </Field>
          <Field label={t("severity")}>
            {r.riskOfficial ?? (
              <>
                {t("notGraded")} <span className="text-slate-700">— {t("notGradedNote")}</span>
              </>
            )}
          </Field>
          {r.productType !== "food" && <Field label={t("productType")}>{productType}</Field>}
          {r.hazardText && <Field label={t("hazard")}>{truncate(r.hazardText, 200)}</Field>}
          {r.hazardCategories.length > 0 && (
            <Field label={t("hazardCategories")}>
              <Values values={r.hazardCategories} t={t} />
            </Field>
          )}
          {r.productCategories.length > 0 && (
            <Field label={t("productCategories")}>
              <Values values={r.productCategories} t={t} />
            </Field>
          )}
          {r.originCountries.length > 0 && (
            <Field label={t("originCountries")}>
              <Values values={r.originCountries} t={t} />
            </Field>
          )}
        </dl>
      </article>
    </li>
  );
}
