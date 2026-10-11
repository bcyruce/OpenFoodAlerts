import { getTranslations } from "next-intl/server";
import Link from "next/link";
import { notFound } from "next/navigation";
import { isSiteLocale } from "@/i18n/routing";

// Placeholder until the home page (ticket 26). Not available in zh (spec §9).
export default async function Home({ params }: PageProps<"/[locale]">) {
  const { locale } = await params;
  if (!isSiteLocale(locale)) notFound();
  const t = await getTranslations({ locale });
  return (
    <>
      <h1 className="text-2xl font-semibold">{t("Site.name")}</h1>
      <p className="mt-2 text-slate-700">{t("Site.tagline")}</p>
      <p className="mt-4 text-slate-700">{t("Home.intro")}</p>
      <p className="mt-4">
        <Link href={`/${locale}/alerts`}>{t("Home.subscribe")}</Link>
      </p>
    </>
  );
}
