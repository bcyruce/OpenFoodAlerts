import type { Metadata } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getMessages, getTranslations } from "next-intl/server";
import { ConfirmSubscription } from "@/components/confirm-subscription";

// Landing page of the confirmation link (spec §9). The token is in the URL fragment, so
// it never reaches server logs or Referer headers; the button posts it to /api/confirm.
export async function generateMetadata({
  params,
}: PageProps<"/[locale]/alerts/confirm">): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "AlertsConfirm" });
  return { title: t("metaTitle"), robots: { index: false, follow: false } };
}

export default async function ConfirmPage({ params }: PageProps<"/[locale]/alerts/confirm">) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "AlertsConfirm" });
  const messages = await getMessages({ locale });
  return (
    <>
      <h1 className="text-2xl font-semibold">{t("heading")}</h1>
      <NextIntlClientProvider locale={locale} messages={{ AlertsConfirm: messages.AlertsConfirm }}>
        <ConfirmSubscription formPath={`/${locale}/alerts`} />
      </NextIntlClientProvider>
    </>
  );
}
