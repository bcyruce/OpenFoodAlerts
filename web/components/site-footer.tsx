import { getTranslations } from "next-intl/server";
import type { Locale } from "@/i18n/routing";
import { OWNER_NAME, ownerName, snelvinkUrl } from "@/lib/referral";
import { REPO_URL } from "@/lib/site";
import { footerLinks } from "@/lib/site-links";

/**
 * Site-wide footer: links to the data and legal pages, the disclaimer (spec §11.3), the
 * Source attribution and "Built by …, founder of SnelVink" (spec §11.3 rule 1, UTM medium
 * `footer`). Plain text and links only: no banner, no ad.
 */
export async function SiteFooter({ locale }: { locale: Locale }) {
  const t = await getTranslations({ locale, namespace: "Footer" });
  return (
    <footer className="border-t border-slate-200 bg-slate-50" data-testid="site-footer">
      <div className="mx-auto max-w-4xl space-y-3 px-4 py-8 text-sm text-slate-700">
        <nav aria-label={t("linksLabel")}>
          <ul className="flex flex-wrap gap-x-4 gap-y-2">
            {footerLinks(locale).map((link) => (
              <li key={link.key}>
                <a href={link.href} hrefLang={link.hrefLang}>
                  {t(link.key)}
                </a>
              </li>
            ))}
            <li>
              <a href={REPO_URL}>{t("sourceCode")}</a>
            </li>
          </ul>
        </nav>
        <p data-testid="footer-disclaimer">{t("disclaimer")}</p>
        <p data-testid="footer-sources">{t("attribution")}</p>
        <p data-testid="footer-built-by">
          {t.rich("builtBy", {
            name: ownerName(OWNER_NAME, t("ownerPlaceholder")),
            link: (chunks) => <a href={snelvinkUrl("footer")}>{chunks}</a>,
          })}
        </p>
      </div>
    </footer>
  );
}
