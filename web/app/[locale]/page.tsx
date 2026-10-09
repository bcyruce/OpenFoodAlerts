import { getTranslations } from "next-intl/server";

// Placeholder until the home page (ticket 26).
export default async function Home({ params }: PageProps<"/[locale]">) {
  const { locale } = await params;
  const t = await getTranslations({ locale });
  return (
    <>
      <h1 className="text-2xl font-semibold">{t("Site.name")}</h1>
      <p className="mt-2 text-slate-700">{t("Site.tagline")}</p>
      <p className="mt-4 text-slate-700">{t("Home.intro")}</p>
    </>
  );
}
