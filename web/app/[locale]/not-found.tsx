import { getTranslations } from "next-intl/server";
import Link from "next/link";
import { locale as rootLocale } from "next/root-params";

export default async function NotFound() {
  const locale = await rootLocale();
  const t = await getTranslations({ locale, namespace: "Notification" });
  return (
    <>
      <h1 className="text-2xl font-semibold">{t("notFoundTitle")}</h1>
      <p className="mt-2 text-slate-700">{t("notFoundBody")}</p>
      <p className="mt-4">
        <Link href={`/${locale}`}>{t("backHome")}</Link>
      </p>
    </>
  );
}
