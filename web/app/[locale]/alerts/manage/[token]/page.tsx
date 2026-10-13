import type { Metadata } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getMessages, getTranslations } from "next-intl/server";
import { ManageSubscription } from "@/components/manage-subscription";
import type { Locale } from "@/i18n/routing";
import { getDb } from "@/lib/db";
import { localizeCatalog } from "@/lib/subscriptions/catalog";
import { tokenFromLink } from "@/lib/subscriptions/links";
import { findSubscription } from "@/lib/subscriptions/manage";
import { loadFilterCatalog } from "@/lib/subscriptions/runtime";

// The manage link from every Digest and Instant email (spec §9). The token is in the path,
// as the spec has it: the page works when opened from any mail client, and the same token
// is in the List-Unsubscribe URL anyway. Opening it changes nothing (mail scanners open
// links); every change is a button. It is rendered per request and never cached
// (no generateStaticParams), never indexed, and sent with `Referrer-Policy: no-referrer`
// (next.config.ts), so the token does not leak through Referer headers.
export const instant = false;

export async function generateMetadata({
  params,
}: PageProps<"/[locale]/alerts/manage/[token]">): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "Manage" });
  return { title: t("metaTitle"), robots: { index: false, follow: false }, referrer: "no-referrer" };
}

export default async function ManagePage({ params }: PageProps<"/[locale]/alerts/manage/[token]">) {
  const { locale: raw, token: rawToken } = await params;
  const locale = raw as Locale;
  const t = await getTranslations({ locale, namespace: "Manage" });
  const token = tokenFromLink(rawToken);
  const subscription = token ? await findSubscription(getDb(), token) : null;
  const formPath = `/${locale}/alerts`;

  if (!token || !subscription) {
    return (
      <>
        <h1 className="text-2xl font-semibold">{t("invalidHeading")}</h1>
        <p className="mt-4 max-w-prose">{t("invalid")}</p>
        <p className="mt-4">
          <a href={formPath}>{t("subscribeAgain")}</a>
        </p>
      </>
    );
  }

  const messages = await getMessages({ locale });
  const catalog = localizeCatalog(await loadFilterCatalog(), locale);
  return (
    <>
      <h1 className="text-2xl font-semibold">{t("heading")}</h1>
      <NextIntlClientProvider
        locale={locale}
        timeZone="Europe/Amsterdam"
        messages={{ Alerts: messages.Alerts, Manage: messages.Manage }}
      >
        <ManageSubscription token={token} subscription={subscription} catalog={catalog} formPath={formPath} />
      </NextIntlClientProvider>
    </>
  );
}
