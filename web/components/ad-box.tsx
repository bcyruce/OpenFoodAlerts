import { getTranslations } from "next-intl/server";
import type { Locale } from "@/i18n/routing";
import { snelvinkUrl } from "@/lib/referral";
import { AdBoxGuard } from "./ad-box-guard";

/**
 * The one SnelVink ad box (spec §11.3): at the bottom of the home page and on /zh/* pages
 * only, enforced by `AdBoxGuard` (see `lib/ad-box.ts`). Labelled as an advertisement and set
 * apart from the content (Nederlandse Reclame Code art. 11.1). No images, animation or
 * tracking beyond the UTM parameters; the link opens in the same window.
 *
 * Place it as the last element of the page content: `<AdBox locale={locale} />`. The UTM
 * medium follows the locale: `zh_box` on Chinese pages, else `home_box`.
 */
export async function AdBox({ locale }: { locale: Locale }) {
  const t = await getTranslations({ locale, namespace: "AdBox" });
  const href = snelvinkUrl(locale === "zh" ? "zh_box" : "home_box");
  return (
    <AdBoxGuard>
      <aside
        aria-labelledby="ad-box-label"
        data-testid="ad-box"
        className="mt-16 border-t border-slate-300 pt-8"
      >
        <div className="rounded-md border border-slate-300 bg-slate-100 p-4 text-sm text-slate-800">
          {/* The fixed label of spec §11.3 rule 4, the same in every locale. */}
          <p id="ad-box-label" lang="nl" className="text-xs font-medium text-slate-700">
            Advertentie / <span lang="zh-Hans">广告</span> — van de maker van deze site
          </p>
          <p className="mt-2">
            <span className="font-semibold">SnelVink</span>: {t("body")}
          </p>
          <p className="mt-2">
            <a href={href} rel="sponsored noopener" className="font-medium">
              {t("cta")}
            </a>
          </p>
        </div>
      </aside>
    </AdBoxGuard>
  );
}
