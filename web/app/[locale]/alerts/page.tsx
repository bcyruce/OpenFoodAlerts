import type { Metadata } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getMessages, getTranslations } from "next-intl/server";
import { SubscriptionForm } from "@/components/subscription-form";
import type { Locale } from "@/i18n/routing";
import { localizeCatalog } from "@/lib/subscriptions/catalog";
import { CONSENT_TEXT_VERSION, consentText } from "@/lib/subscriptions/consent";
import { loadFilterCatalog } from "@/lib/subscriptions/runtime";

// Subscription form (spec §9): en, nl and zh; never indexed.
export async function generateMetadata({ params }: PageProps<"/[locale]/alerts">): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "Alerts" });
  return {
    title: t("metaTitle"),
    description: t("metaDescription"),
    robots: { index: false, follow: false },
  };
}

export default async function AlertsPage({ params }: PageProps<"/[locale]/alerts">) {
  const locale = (await params).locale as Locale;
  const t = await getTranslations({ locale, namespace: "Alerts" });
  const messages = await getMessages({ locale });
  const catalog = localizeCatalog(await loadFilterCatalog(), locale);
  return (
    <>
      <h1 className="text-2xl font-semibold">{t("heading")}</h1>
      <p className="mt-2 max-w-prose text-slate-700">{t("intro")}</p>
      <NextIntlClientProvider locale={locale} messages={{ Alerts: messages.Alerts }}>
        <SubscriptionForm
          locale={locale}
          catalog={catalog}
          consentText={consentText(locale)}
          consentTextVersion={CONSENT_TEXT_VERSION}
        />
      </NextIntlClientProvider>
    </>
  );
}
