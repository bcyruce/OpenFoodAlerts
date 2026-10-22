import { getMessages, getTranslations } from "next-intl/server";
import type { ReactNode } from "react";
import { UNKNOWN_COUNTRY, type AiField, type AiSummary } from "@/lib/ai";
import { formatDate, formatValue } from "@/lib/format";
import type { FieldChange, NotificationDetail } from "@/lib/notifications";
import { AiBadge } from "./ai-badge";
import { aiBadgeWriter } from "./ai-badge-text";

type Props = {
  locale: string;
  notification: NotificationDetail;
  /** Current AI classifications (T5 never included) and the T6 summary in `locale`. */
  ai: { fields: AiField[]; summary: AiSummary | null };
  reportErrorHref: string;
};

/** Language of the Source's own text, for T3 spans quoted from it. */
const SOURCE_LANGUAGE: Record<string, string> = { nvwa: "nl", openfda: "en", rasff: "en" };

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="border-t border-slate-200 py-2 first:border-t-0 sm:grid sm:grid-cols-[13rem_minmax(0,1fr)] sm:gap-4">
      <dt className="font-medium text-slate-700">{label}</dt>
      <dd className="mt-1 whitespace-pre-line break-words text-slate-900 sm:mt-0">{children}</dd>
    </div>
  );
}

/** Official fields, the AI area (badged, apart), version history and attribution. */
export async function NotificationDetailView({
  locale,
  notification: n,
  ai,
  reportErrorHref,
}: Props) {
  const t = await getTranslations({ locale, namespace: "Notification" });
  const tAi = await getTranslations({ locale, namespace: "Ai" });
  const tAll = await getTranslations({ locale });
  const badge = await aiBadgeWriter(locale);
  const sourceFieldLabel = (key: string) =>
    tAll.has(`SourceFields.${n.source.code}.${key}`)
      ? tAll(`SourceFields.${n.source.code}.${key}`)
      : key.replaceAll("_", " ");
  const fieldLabel = (field: string) => {
    if (field.startsWith("source_fields.")) return sourceFieldLabel(field.slice(14));
    return tAll.has(`Fields.${field}`) ? tAll(`Fields.${field}`) : field;
  };
  const productType = tAll.has(`ProductTypes.${n.productType}`)
    ? tAll(`ProductTypes.${n.productType}`)
    : n.productType;
  const productTypeIsAi = n.productTypeProvenance === "ai";
  // Known fields in the order of the message file, then any others alphabetically.
  const messages = await getMessages({ locale });
  const known = Object.keys(
    (messages.SourceFields as Record<string, Record<string, string>> | undefined)?.[
      n.source.code
    ] ?? {},
  );
  const rank = (k: string) => (known.includes(k) ? known.indexOf(k) : known.length);
  const sourceFields = Object.entries(n.sourceFields)
    .filter(([, v]) => v !== null && v !== undefined && v !== "")
    .sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b));
  const show = (v: unknown) => formatValue(locale, v) || t("empty");

  return (
    <article aria-labelledby="notification-title" className="space-y-8">
      <header>
        <p className="text-sm font-medium text-slate-700">
          {n.source.name} · {n.notificationType}
        </p>
        <h1 id="notification-title" className="mt-1 text-3xl font-semibold break-words text-slate-900">
          {n.title}
        </h1>
        <p className="mt-2 text-slate-700">
          {/* NVWA keys are long URL paths: let them wrap on phones. */}
          {t("reference")}: <span className="font-mono break-all">{n.sourceKey}</span>
        </p>
      </header>

      <section
        aria-labelledby="official-heading"
        data-testid="official-fields"
        className="rounded-lg border border-slate-300 bg-white p-5"
      >
        <h2 id="official-heading" className="text-xl font-semibold">
          {t("officialHeading")}
        </h2>
        <p className="mt-1 text-sm text-slate-700">{t("officialIntro")}</p>
        <dl className="mt-4">
          <Row label={t("source")}>{n.source.name}</Row>
          <Row label={t("notificationType")}>{n.notificationType}</Row>
          <Row label={t("severity")}>
            {n.riskOfficial ?? (
              <>
                <strong>{t("notGraded")}</strong>{" "}
                <span className="text-slate-700">— {t("notGradedNote")}</span>
              </>
            )}
          </Row>
          {n.statusOfficial && <Row label={t("status")}>{n.statusOfficial}</Row>}
          {n.publishedAt && (
            <Row label={t("publishedAt")}>
              <time dateTime={n.publishedAt}>{formatDate(locale, n.publishedAt)}</time>
            </Row>
          )}
          {n.sourceUpdatedAt && (
            <Row label={t("sourceUpdatedAt")}>
              <time dateTime={n.sourceUpdatedAt}>{formatDate(locale, n.sourceUpdatedAt, true)}</time>
            </Row>
          )}
          {!productTypeIsAi && (
            <Row label={t("productType")}>
              {productType}{" "}
              <span className="text-sm text-slate-700">
                (
                {n.productTypeProvenance === "official"
                  ? t("productTypeOfficial")
                  : t("productTypeRule")}
                )
              </span>
            </Row>
          )}
          {n.productText && <Row label={t("product")}>{n.productText}</Row>}
          {n.hazardText && <Row label={t("hazard")}>{n.hazardText}</Row>}
          {n.summarySource && <Row label={t("summarySource")}>{n.summarySource}</Row>}
        </dl>

        {sourceFields.length > 0 && (
          <>
            <h3 className="mt-6 text-lg font-semibold">
              {t("sourceFieldsHeading", { source: n.source.name })}
            </h3>
            <dl className="mt-2" data-testid="source-fields">
              {sourceFields.map(([key, value]) => (
                <Row key={key} label={sourceFieldLabel(key)}>
                  {formatValue(locale, value)}
                </Row>
              ))}
            </dl>
          </>
        )}

        <p className="mt-6">
          <a href={n.sourceUrl} rel="external noopener" className="font-medium">
            {t("officialLink", { source: n.source.name })}
          </a>
        </p>
      </section>

      {/* AI classifications: always badged, dashed and apart from the official fields. T5
          (Product type) is internal and never shown (spec §6.1). */}
      <section
        aria-labelledby="ai-heading"
        data-testid="ai-fields"
        className="rounded-lg border-2 border-dashed border-violet-400 bg-violet-50 p-5"
      >
        <h2 id="ai-heading" className="text-xl font-semibold text-violet-950">
          {t("aiHeading")}
        </h2>
        <p className="mt-1 text-sm text-slate-800">{t("aiIntro")}</p>
        {ai.fields.length === 0 && !ai.summary && (
          <p className="mt-4 text-slate-800">{t("aiEmpty")}</p>
        )}
        {ai.fields.length > 0 && (
          <dl className="mt-4">
            {ai.fields.map((f) => (
              <Row key={f.task} label={tAi(`field.${f.task}`)}>
                <span
                  className="inline-flex flex-wrap items-start gap-2"
                  data-testid="ai-value"
                  data-task={f.task}
                >
                  <AiBadge {...badge(f, n.sourceUrl)} />
                  {f.value === null ? (
                    <span className="text-slate-800">{tAi("abstained")}</span>
                  ) : f.task === "origin_country" && f.value === UNKNOWN_COUNTRY ? (
                    <span className="text-slate-800">{tAi("unknownCountry")}</span>
                  ) : f.task === "hazard" ? (
                    <q lang={SOURCE_LANGUAGE[n.source.code]}>{f.label}</q>
                  ) : (
                    <span>{f.label}</span>
                  )}
                </span>
              </Row>
            ))}
          </dl>
        )}
        {ai.summary && (
          <section aria-labelledby="ai-summary-heading" data-testid="ai-summary" className="mt-4">
            <h3 id="ai-summary-heading" className="font-semibold">
              {tAi("summaryHeading")}{" "}
              <span className="font-normal text-slate-800">({tAi("aiGenerated")})</span>
            </h3>
            <p className="mt-1 flex flex-wrap items-start gap-2">
              <AiBadge {...badge(ai.summary, n.sourceUrl)} />
              <span>{ai.summary.text}</span>
            </p>
          </section>
        )}
      </section>

      <section aria-labelledby="history-heading" data-testid="version-history">
        <h2 id="history-heading" className="text-xl font-semibold">
          {t("historyHeading")}
        </h2>
        <p className="mt-1 text-sm text-slate-700">{t("historyIntro")}</p>
        <dl className="mt-4">
          <Row label={t("firstSeenAt")}>
            <time dateTime={n.firstSeenAt}>{formatDate(locale, n.firstSeenAt, true)}</time>
          </Row>
          <Row label={t("lastChangedAt")}>
            <time dateTime={n.lastChangedAt}>{formatDate(locale, n.lastChangedAt, true)}</time>
          </Row>
        </dl>
        <ol className="mt-4 space-y-4">
          {n.versions.map((v) => (
            <li key={v.version} className="rounded-lg border border-slate-200 p-4">
              <h3 className="font-semibold">
                {t("version", { version: v.version })}{" "}
                <span className="font-normal text-slate-700">
                  —{" "}
                  {t("observedAt", { date: formatDate(locale, v.observedAt, true) })}
                </span>
                {v.isSubstantial && (
                  <span className="ml-2 rounded bg-amber-100 px-2 py-0.5 text-sm font-medium text-amber-900">
                    {t("substantial")}
                  </span>
                )}
              </h3>
              {v.changes.length === 0 ? (
                <p className="mt-2 text-slate-700">
                  {v.version === 1 ? t("firstVersion") : t("noFieldChanges")}
                </p>
              ) : (
                <ChangesTable
                  changes={v.changes}
                  caption={t("version", { version: v.version })}
                  labels={{ field: t("field"), old: t("oldValue"), new: t("newValue") }}
                  fieldLabel={fieldLabel}
                  show={show}
                />
              )}
            </li>
          ))}
        </ol>
      </section>

      <section
        aria-labelledby="attribution-heading"
        className="border-t border-slate-200 pt-6 text-sm text-slate-800"
      >
        <h2 id="attribution-heading" className="text-base font-semibold">
          {t("attributionHeading")}
        </h2>
        <p className="mt-1" data-testid="attribution">
          {n.source.attributionText}
        </p>
        <p className="mt-1">{t("license", { license: n.source.license })}</p>
        <p className="mt-3">
          <a href={reportErrorHref} rel="noopener">
            {t("reportError")}
          </a>{" "}
          <span className="text-slate-700">{t("reportErrorNote")}</span>
        </p>
      </section>
    </article>
  );
}

function ChangesTable({
  changes,
  caption,
  labels,
  fieldLabel,
  show,
}: {
  changes: FieldChange[];
  caption: string;
  labels: { field: string; old: string; new: string };
  fieldLabel: (field: string) => string;
  show: (value: unknown) => string;
}) {
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full border-collapse text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-slate-300">
            <th scope="col" className="py-1 pr-4 font-semibold">
              {labels.field}
            </th>
            <th scope="col" className="py-1 pr-4 font-semibold">
              {labels.old}
            </th>
            <th scope="col" className="py-1 font-semibold">
              {labels.new}
            </th>
          </tr>
        </thead>
        <tbody>
          {changes.map((c) => (
            <tr key={c.field} className="border-b border-slate-200 align-top">
              <th scope="row" className="py-1 pr-4 font-medium">
                {fieldLabel(c.field)}
              </th>
              <td className="py-1 pr-4 break-words">{show(c.old)}</td>
              <td className="py-1 break-words">{show(c.new)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
