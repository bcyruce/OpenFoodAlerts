import { hasLocale } from "next-intl";
import { getTranslations } from "next-intl/server";
import Link from "next/link";
import { locale as rootLocale } from "next/root-params";
import { homePath, routing } from "@/i18n/routing";

export default async function NotFound() {
  const requested = await rootLocale();
  const locale = hasLocale(routing.locales, requested) ? requested : routing.defaultLocale;
  const t = await getTranslations({ locale, namespace: "Notification" });
  return (
    <>
      <h1 className="text-2xl font-semibold">{t("notFoundTitle")}</h1>
      <p className="mt-2 text-slate-700">{t("notFoundBody")}</p>
      <p className="mt-4">
        <Link href={homePath(locale)}>{t("backHome")}</Link>
      </p>
    </>
  );
}
