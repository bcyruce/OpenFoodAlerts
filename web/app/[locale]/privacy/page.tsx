import type { Metadata } from "next";
import { LegalPage, legalMetadata } from "@/components/legal-page";
import { PRIVACY } from "@/content/legal/privacy";
import type { Locale } from "@/i18n/routing";

// Static (spec §9), en/nl/zh. Keep consistent with docs/privacy/ropa.md.
export const ensureStatic = "navigation";

export async function generateMetadata({ params }: PageProps<"/[locale]/privacy">): Promise<Metadata> {
  return legalMetadata("privacy", (await params).locale as Locale);
}

export default async function PrivacyPage({ params }: PageProps<"/[locale]/privacy">) {
  const locale = (await params).locale as Locale;
  const Content = PRIVACY[locale];
  return (
    <LegalPage page="privacy" locale={locale}>
      <Content />
    </LegalPage>
  );
}
