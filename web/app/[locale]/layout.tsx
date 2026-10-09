import type { Metadata } from "next";
import { hasLocale } from "next-intl";
import { getTranslations } from "next-intl/server";
import Link from "next/link";
import { notFound } from "next/navigation";
import { LanguageSwitch } from "@/components/language-switch";
import { routing } from "@/i18n/routing";
import { SITE_URL } from "@/lib/site";
import "../globals.css";

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: { default: "OpenFoodAlerts", template: "%s | OpenFoodAlerts" },
};

export default async function LocaleLayout({ children, params }: LayoutProps<"/[locale]">) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  const t = await getTranslations({ locale, namespace: "Site" });
  return (
    <html lang={locale} className="h-full antialiased">
      <body className="flex min-h-full flex-col">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-10 focus:bg-white focus:px-3 focus:py-2"
        >
          {t("skipToContent")}
        </a>
        <header className="border-b border-slate-200">
          <div className="mx-auto flex max-w-4xl flex-wrap items-center justify-between gap-3 px-4 py-3">
            <Link
              href={`/${locale}`}
              className="text-lg font-semibold text-slate-900 no-underline hover:text-slate-900"
            >
              {t("name")}
            </Link>
            <LanguageSwitch label={t("languageSwitch")} locales={routing.locales} current={locale} />
          </div>
        </header>
        <main id="main" className="mx-auto w-full max-w-4xl flex-1 px-4 py-8">
          {children}
        </main>
        <footer className="border-t border-slate-200 bg-slate-50">
          <p className="mx-auto max-w-4xl px-4 py-6 text-sm text-slate-700">{t("disclaimer")}</p>
        </footer>
      </body>
    </html>
  );
}
