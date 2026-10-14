import type { Metadata } from "next";
import { LegalPage, legalMetadata } from "@/components/legal-page";
import { DISCLAIMER } from "@/content/legal/disclaimer";
import type { Locale } from "@/i18n/routing";

// Static (spec §9), en/nl/zh. The statement is the text of spec §11.3.
export const ensureStatic = "navigation";

export async function generateMetadata({ params }: PageProps<"/[locale]/disclaimer">): Promise<Metadata> {
  return legalMetadata("disclaimer", (await params).locale as Locale);
}

export default async function DisclaimerPage({ params }: PageProps<"/[locale]/disclaimer">) {
  const locale = (await params).locale as Locale;
  const Content = DISCLAIMER[locale];
  return (
    <LegalPage page="disclaimer" locale={locale}>
      <Content />
    </LegalPage>
  );
}
