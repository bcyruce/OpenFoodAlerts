/**
 * Email templates. Strings live in messages/{locale}.json under `Email`, so emails use
 * the same translation files as the site.
 */
import { createTranslator } from "next-intl";
import en from "@/messages/en.json";
import nl from "@/messages/nl.json";
import zh from "@/messages/zh.json";
import type {
  SourceCode,
  SubscriptionFilters,
  SubscriptionLocale,
} from "@/lib/subscriptions/validate";
import { renderEmail, type RenderedEmail } from "./render";

const MESSAGES = { en, nl, zh } as const;

export const SOURCE_NAMES: Record<SourceCode, string> = {
  rasff: "RASFF",
  nvwa: "NVWA",
  openfda: "openFDA",
};

export function emailTranslator(locale: SubscriptionLocale) {
  return createTranslator({ locale, messages: MESSAGES[locale], namespace: "Email" });
}

export type ConfirmEmailInput = {
  locale: SubscriptionLocale;
  /** Absolute link to /{locale}/alerts/confirm with the token. */
  confirmUrl: string;
  filters: SubscriptionFilters;
  includeUnclassified: boolean;
  instantSources: SourceCode[];
};

export function renderConfirmEmail(input: ConfirmEmailInput): RenderedEmail {
  const t = emailTranslator(input.locale);
  const { filters } = input;
  const sourceList = (codes: SourceCode[], empty: string) =>
    codes.length === 0 ? empty : codes.map((c) => SOURCE_NAMES[c]).join(", ");
  const count = (values: unknown[]) =>
    values.length === 0 ? t("confirm.all") : t("confirm.selected", { count: values.length });

  return renderEmail({
    locale: input.locale,
    subject: t("confirm.subject"),
    blocks: [
      { kind: "paragraph", text: t("confirm.intro") },
      {
        kind: "list",
        items: [
          t("confirm.sources", { value: sourceList(filters.sources, t("confirm.all")) }),
          t("confirm.hazardCategories", { value: count(filters.hazard_categories) }),
          t("confirm.productCategories", { value: count(filters.product_categories) }),
          t("confirm.originCountries", { value: count(filters.origin_countries) }),
          t("confirm.unclassified", {
            value: input.includeUnclassified ? t("confirm.included") : t("confirm.excluded"),
          }),
          t("confirm.instant", { value: sourceList(input.instantSources, t("confirm.none")) }),
        ],
      },
      { kind: "button", label: t("confirm.button"), url: input.confirmUrl },
      { kind: "note", text: t("confirm.validity") },
      { kind: "note", text: t("confirm.ignore") },
    ],
    footer: [t("footer"), t("reason", { site: new URL(input.confirmUrl).host })],
  });
}
