"use client";

import { useTranslations } from "next-intl";
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { SOURCES, type FilterSource, type Filters } from "@/lib/filters";
import type { SourceStats, StatsResponse } from "@/lib/stats";
import {
  DIMENSIONS,
  HEATMAP_PAIRS,
  MONTH_PRESETS,
  parseStatsQuery,
  toStatsParams,
  type StatsQuery,
} from "@/lib/stats-query";
import { formatMonth, pairLabel, timeSeriesTable } from "@/lib/stats-tables";
import type { FilterOption, LocalizedCatalog } from "@/lib/subscriptions/catalog";
import { Chart } from "./chart";
import {
  heatmapHeight,
  heatmapOption,
  SOURCE_COLORS,
  timeSeriesOption,
  topHeight,
  topOption,
} from "./options";

const SOURCE_NAMES: Record<FilterSource, string> = { rasff: "RASFF", nvwa: "NVWA", openfda: "openFDA" };
/** Filters key and URL parameter of each dimension. */
const DIMENSION_FILTERS = {
  hazard: { key: "hazardCategories", param: "hazard" },
  product: { key: "productCategories", param: "product" },
  country: { key: "countries", param: "country" },
} as const;

type Status = "idle" | "loading" | "done" | "error";

type Props = {
  locale: string;
  initialQuery: StatsQuery;
  initialStats: StatsResponse;
  catalog: LocalizedCatalog;
};

/**
 * The dashboard (spec §9): filters on the left, charts with data tables on the right. The
 * server renders it with the statistics for the URL; afterwards every filter change
 * fetches /api/stats and replaces the URL (no new history entry), so the address bar can
 * always be shared. The controls are a GET form too, which works without JavaScript.
 */
export function Dashboard({ locale, initialQuery, initialStats, catalog }: Props) {
  const t = useTranslations("Dashboard");
  const [query, setQuery] = useState(initialQuery);
  const [stats, setStats] = useState(initialStats);
  const [status, setStatus] = useState<Status>("idle");
  const pending = useRef<AbortController | null>(null);
  const path = `/${locale}/dashboard`;

  useEffect(() => () => pending.current?.abort(), []);

  async function update(change: StatsQuery) {
    // Through the URL form and back: sorted, deduplicated values, as the server expects.
    const next = parseStatsQuery(toStatsParams(change));
    const params = toStatsParams(next);
    setQuery(next);
    window.history.replaceState(null, "", params.size > 0 ? `${path}?${params}` : path);
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    setStatus("loading");
    try {
      params.set("locale", locale);
      const response = await fetch(`/api/stats?${params}`, { signal: controller.signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setStats((await response.json()) as StatsResponse);
      setStatus("done");
    } catch (e) {
      if (controller.signal.aborted) return;
      console.error(e);
      setStatus("error");
    }
  }

  const setFilters = (change: Partial<Filters>, months = query.months) =>
    update({ months, filters: { ...query.filters, ...change } });

  return (
    <div className="mt-6 lg:grid lg:grid-cols-[16rem_1fr] lg:gap-8">
      <Controls
        path={path}
        query={query}
        catalog={catalog}
        onFilters={setFilters}
        onPeriod={(months) => setFilters({ from: null, to: null }, months)}
      />
      <div className="mt-8 min-w-0 lg:mt-0">
        <p role="status" className="min-h-6 text-sm text-slate-700" data-testid="dashboard-status">
          {status === "loading" ? t("updating") : status === "done" ? t("updated") : ""}
          {status === "error" && <span className="font-medium text-red-800">{t("error")}</span>}
        </p>
        <div
          aria-busy={status === "loading"}
          className={status === "loading" ? "opacity-60 transition-opacity" : "transition-opacity"}
        >
          <Results locale={locale} stats={stats} />
        </div>
      </div>
    </div>
  );
}

function Controls({
  path,
  query,
  catalog,
  onFilters,
  onPeriod,
}: {
  path: string;
  query: StatsQuery;
  catalog: LocalizedCatalog;
  onFilters: (change: Partial<Filters>) => void;
  onPeriod: (months: number | null) => void;
}) {
  const t = useTranslations("Dashboard");
  const f = query.filters;
  const id = useId();
  const custom = Boolean(f.from || f.to);
  const selectedSources = f.sources.length > 0 ? f.sources : [...SOURCES];
  const presets: number[] = [...MONTH_PRESETS];
  if (query.months !== null && !presets.includes(query.months)) presets.push(query.months);
  presets.sort((a, b) => a - b);
  const period = custom ? "custom" : query.months === null ? "all" : String(query.months);

  const toggleSource = (source: FilterSource, on: boolean) => {
    const next = SOURCES.filter((s) => (s === source ? on : selectedSources.includes(s)));
    onFilters({ sources: next.length === SOURCES.length ? [] : next });
  };

  return (
    <section aria-labelledby={`${id}-heading`}>
      <h2 id={`${id}-heading`} className="text-xl font-semibold">
        {t("filtersHeading")}
      </h2>
      <form action={path} method="get" onSubmit={(e) => e.preventDefault()} data-testid="dashboard-filters">
        <fieldset className="border-t border-slate-200 py-3 first-of-type:border-t-0">
          <legend className="float-left w-full font-medium">{t("source")}</legend>
          <ul className="clear-both space-y-1 pt-2">
            {SOURCES.map((s) => {
              const checked = selectedSources.includes(s);
              return (
                <li key={s}>
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      name="source"
                      value={s}
                      checked={checked}
                      // At least one Source stays selected.
                      disabled={checked && selectedSources.length === 1}
                      aria-describedby={`${id}-source-hint`}
                      onChange={(e) => toggleSource(s, e.target.checked)}
                    />
                    <span
                      aria-hidden="true"
                      className="inline-block h-3 w-3 rounded-sm"
                      style={{ background: SOURCE_COLORS[s] }}
                    />
                    {SOURCE_NAMES[s]}
                  </label>
                </li>
              );
            })}
          </ul>
          <p id={`${id}-source-hint`} className="mt-1 text-sm text-slate-700">
            {t("sourceHint")}
          </p>
        </fieldset>

        <fieldset className="border-t border-slate-200 py-3">
          <legend id={`${id}-period`} className="float-left w-full font-medium">
            {t("period")}
          </legend>
          <div className="clear-both pt-2">
            <select
              aria-labelledby={`${id}-period`}
              name="months"
              value={period}
              onChange={(e) => {
                const v = e.target.value;
                if (v !== "custom") onPeriod(v === "all" ? null : Number(v));
              }}
              className="w-full rounded border border-slate-500 bg-white px-2 py-1.5"
            >
              {presets.map((m) => (
                <option key={m} value={String(m)}>
                  {t("periodMonths", { count: m })}
                </option>
              ))}
              <option value="all">{t("periodAll")}</option>
              {custom && (
                <option value="custom" disabled>
                  {t("periodCustom")}
                </option>
              )}
            </select>
            <div className="mt-2 grid grid-cols-2 gap-2 text-sm">
              <label>
                <span className="block text-slate-700">{t("from")}</span>
                <input
                  type="date"
                  name="from"
                  value={f.from ?? ""}
                  onChange={(e) => onFilters({ from: e.target.value || null })}
                  className="w-full rounded border border-slate-500 px-1 py-1"
                />
              </label>
              <label>
                <span className="block text-slate-700">{t("to")}</span>
                <input
                  type="date"
                  name="to"
                  value={f.to ?? ""}
                  onChange={(e) => onFilters({ to: e.target.value || null })}
                  className="w-full rounded border border-slate-500 px-1 py-1"
                />
              </label>
            </div>
          </div>
        </fieldset>

        {DIMENSIONS.map((d) => {
          const { key, param } = DIMENSION_FILTERS[d];
          const options = (d === "hazard"
            ? catalog.hazardCategories
            : d === "product"
              ? catalog.productCategories
              : catalog.countries) as FilterOption<string | number>[];
          return (
            <ValueGroup
              key={d}
              legend={t(`dimension.${d}`)}
              param={param}
              options={options}
              selected={f[key] as (string | number)[]}
              onChange={(values) => onFilters({ [key]: values } as Partial<Filters>)}
            />
          );
        })}

        <div className="border-t border-slate-200 py-3">
          <label className="flex items-start gap-2 font-medium">
            <input
              type="checkbox"
              name="official_only"
              value="1"
              checked={f.officialOnly}
              onChange={(e) => onFilters({ officialOnly: e.target.checked })}
              aria-describedby={`${id}-official-hint`}
              className="mt-1"
            />
            {t("officialOnly")}
          </label>
          <p id={`${id}-official-hint`} className="mt-1 text-sm text-slate-700">
            {t("officialOnlyHint")}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-4 border-t border-slate-200 pt-3">
          <noscript>
            <button
              type="submit"
              className="rounded bg-blue-700 px-4 py-2 font-medium text-white hover:bg-blue-800"
            >
              {t("apply")}
            </button>
          </noscript>
          <a href={path}>{t("reset")}</a>
        </div>
      </form>
    </section>
  );
}

/** Checkboxes for one dimension, with a text box that narrows the list. */
function ValueGroup<T extends string | number>({
  legend,
  param,
  options,
  selected,
  onChange,
}: {
  legend: string;
  param: string;
  options: FilterOption<T>[];
  selected: T[];
  onChange: (values: T[]) => void;
}) {
  const t = useTranslations("Dashboard");
  const [text, setText] = useState("");
  const id = useId();
  const q = text.trim().toLocaleLowerCase();
  const isSelected = (v: T) => selected.includes(v);
  // Selected values first, so they stay in view.
  const listed = options
    .filter((o) => isSelected(o.value) || !q || o.label.toLocaleLowerCase().includes(q))
    .sort((a, b) => Number(isSelected(b.value)) - Number(isSelected(a.value)));
  return (
    <details
      className="border-t border-slate-200 py-3"
      open={selected.length > 0}
      data-testid={`filter-${param}`}
    >
      <summary className="cursor-pointer font-medium">
        {legend}{" "}
        <span className="font-normal text-slate-700">
          ({selected.length > 0 ? t("selectedCount", { count: selected.length }) : t("selectedNone")})
        </span>
      </summary>
      <fieldset className="mt-2">
        <legend className="sr-only">{legend}</legend>
        <label htmlFor={`${id}-q`} className="sr-only">
          {t("filterList")}
        </label>
        <input
          id={`${id}-q`}
          type="search"
          placeholder={t("filterList")}
          value={text}
          onChange={(e) => setText(e.target.value)}
          className="mb-2 w-full rounded border border-slate-500 px-2 py-1 text-sm"
        />
        <ul className="max-h-56 space-y-1 overflow-y-auto pr-1 text-sm">
          {listed.map((o) => (
            <li key={String(o.value)}>
              <label className="flex items-start gap-2">
                <input
                  type="checkbox"
                  name={param}
                  value={String(o.value)}
                  checked={isSelected(o.value)}
                  onChange={(e) =>
                    onChange(
                      e.target.checked
                        ? [...selected, o.value]
                        : selected.filter((v) => v !== o.value),
                    )
                  }
                  className="mt-0.5"
                />
                <span>{o.label}</span>
              </label>
            </li>
          ))}
        </ul>
        {selected.length > 0 && (
          <button
            type="button"
            onClick={() => onChange([])}
            className="mt-2 text-sm text-blue-800 underline"
          >
            {t("clearSelection")}
          </button>
        )}
      </fieldset>
    </details>
  );
}

/** Totals, the time series and, per Source, the heatmap and the Top-N charts. */
export function Results({ locale, stats }: { locale: string; stats: StatsResponse }) {
  const t = useTranslations("Dashboard");
  const number = useMemo(() => new Intl.NumberFormat(locale), [locale]);
  const series = useMemo(() => timeSeriesOption(stats, locale), [stats, locale]);
  const table = timeSeriesTable(stats);
  return (
    <div className="space-y-10">
      <section aria-labelledby="totals-heading">
        <h2 id="totals-heading" className="text-xl font-semibold">
          {t("totalsHeading")}
        </h2>
        <ul className="mt-3 grid gap-3 sm:grid-cols-3">
          {stats.sources.map((s) => (
            <li
              key={s.source}
              className="rounded-lg border border-slate-300 p-3"
              data-testid={`total-${s.source}`}
            >
              <p className="flex items-center gap-2 font-medium">
                <span
                  aria-hidden="true"
                  className="inline-block h-3 w-3 rounded-sm"
                  style={{ background: SOURCE_COLORS[s.source] }}
                />
                {s.label}
              </p>
              <p className="mt-1 text-xl font-semibold text-slate-900">
                {t("total", { count: s.total })}
              </p>
              <p className="mt-1 text-sm text-slate-700">
                {t("classifiedNote", {
                  hazard: number.format(s.classified.hazard),
                  product: number.format(s.classified.product),
                  country: number.format(s.classified.country),
                })}
              </p>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-sm text-slate-700">{t("scopeNote")}</p>
      </section>

      <section aria-labelledby="timeseries-heading">
        <h2 id="timeseries-heading" className="text-xl font-semibold">
          {t("timeSeriesHeading")}
        </h2>
        <Chart option={series} label={t("timeSeriesLabel")} height={280} testId="chart-timeseries" />
        <DataTable testId="table-timeseries" label={t("timeSeriesHeading")}>
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
              <th scope="row">{t("totalColumn")}</th>
              {table.totals.map((c, i) => (
                <td key={table.columns[i]} className="text-right font-semibold">
                  {number.format(c)}
                </td>
              ))}
            </tr>
          </tfoot>
        </DataTable>
      </section>

      {stats.sources.map((s) => (
        <SourceSection key={s.source} locale={locale} months={stats.months} stats={s} />
      ))}
    </div>
  );
}

function SourceSection({ locale, months, stats: s }: { locale: string; months: string[]; stats: SourceStats }) {
  const t = useTranslations("Dashboard");
  const number = new Intl.NumberFormat(locale);
  const heading = `${s.source}-heading`;
  const heatmap = useMemo(() => heatmapOption(s.heatmap, months, locale), [s.heatmap, months, locale]);
  return (
    <section aria-labelledby={heading} data-testid={`source-${s.source}`} className="space-y-6">
      <h2 id={heading} className="flex items-center gap-2 border-b border-slate-300 pb-1 text-2xl font-semibold">
        <span aria-hidden="true" className="inline-block h-4 w-4 rounded-sm" style={{ background: SOURCE_COLORS[s.source] }} />
        {s.label}
      </h2>

      <section aria-labelledby={`${heading}-heatmap`}>
        <h3 id={`${heading}-heatmap`} className="text-lg font-semibold">
          {t("heatmapHeading")}
        </h3>
        {s.heatmap.length === 0 ? (
          <p className="mt-1 text-slate-700">{t("heatmapEmpty")}</p>
        ) : (
          <>
            <p className="mt-1 text-sm text-slate-700">{t("heatmapHint", { count: HEATMAP_PAIRS })}</p>
            <Chart
              option={heatmap}
              label={t("heatmapLabel")}
              height={heatmapHeight(s.heatmap.length)}
              testId={`chart-heatmap-${s.source}`}
            />
            <DataTable testId={`table-heatmap-${s.source}`} label={`${t("heatmapHeading")}, ${s.label}`}>
              <thead>
                <tr>
                  <th scope="col">{t("pair")}</th>
                  {months.map((m) => (
                    <th key={m} scope="col" className="text-right whitespace-nowrap">
                      {formatMonth(locale, m)}
                    </th>
                  ))}
                  <th scope="col" className="text-right">
                    {t("totalColumn")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {s.heatmap.map((row) => (
                  <tr key={`${row.hazard.value}|${row.country.value}`}>
                    <th scope="row" className="min-w-48">
                      {pairLabel(row)}
                    </th>
                    {row.counts.map((c, i) => (
                      <td key={months[i]} className="text-right">
                        {c > 0 ? number.format(c) : <span className="text-slate-600">0</span>}
                      </td>
                    ))}
                    <td className="text-right font-semibold">{number.format(row.total)}</td>
                  </tr>
                ))}
              </tbody>
            </DataTable>
          </>
        )}
      </section>

      <div className="space-y-6">
        {DIMENSIONS.map((d) => {
          const items = s.top[d];
          const title = t(`topHeading.${d}`);
          return (
            <section key={d} aria-labelledby={`${heading}-top-${d}`} className="min-w-0">
              <h3 id={`${heading}-top-${d}`} className="text-lg font-semibold">
                {title}
              </h3>
              {items.length === 0 ? (
                <p className="mt-1 text-slate-700">{t("topEmpty")}</p>
              ) : (
                <>
                  <Chart
                    option={topOption(items, SOURCE_COLORS[s.source], locale)}
                    label={t("topLabel", { title })}
                    height={topHeight(items.length)}
                    testId={`chart-top-${d}-${s.source}`}
                  />
                  <DataTable testId={`table-top-${d}-${s.source}`} label={`${title}, ${s.label}`}>
                    <thead>
                      <tr>
                        <th scope="col">{t(`dimension.${d}`)}</th>
                        <th scope="col" className="text-right">
                          {t("count")}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((i) => (
                        <tr key={i.value}>
                          <th scope="row">{i.label}</th>
                          <td className="text-right">{number.format(i.count)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </DataTable>
                </>
              )}
            </section>
          );
        })}
      </div>
    </section>
  );
}

/** A chart's data table, collapsed under a disclosure; scrolls sideways when wide. */
function DataTable({
  testId,
  label,
  children,
}: {
  testId: string;
  /** What the table shows (the chart title), for the scrollable region and the caption. */
  label: string;
  children: ReactNode;
}) {
  const t = useTranslations("Dashboard");
  return (
    <details className="mt-2" data-testid={testId}>
      <summary className="cursor-pointer text-sm font-medium text-blue-800">{t("showTable")}</summary>
      <div className="mt-2 overflow-x-auto" tabIndex={0} role="region" aria-label={`${t("showTable")}: ${label}`}>
        <table className="w-full text-sm tabular-nums [&_td]:border-b [&_td]:border-slate-200 [&_td]:px-2 [&_td]:py-1 [&_th]:border-b [&_th]:border-slate-200 [&_th]:px-2 [&_th]:py-1 [&_th:not(.text-right)]:text-left [&_th]:font-medium [&_thead_th]:align-bottom">
          <caption className="sr-only">{label}</caption>
          {children}
        </table>
      </div>
    </details>
  );
}
