import type { Metadata } from "next";
import { LegalPage, legalMetadata } from "@/components/legal-page";
import { COLOFON } from "@/content/legal/colofon";
import type { Locale } from "@/i18n/routing";

// Static (spec §9), en/nl/zh. BW 3:15d fields from lib/legal.ts.
export const ensureStatic = "navigation";

export async function generateMetadata({ params }: PageProps<"/[locale]/colofon">): Promise<Metadata> {
  return legalMetadata("colofon", (await params).locale as Locale);
}

export default async function ColofonPage({ params }: PageProps<"/[locale]/colofon">) {
  const locale = (await params).locale as Locale;
  const Content = COLOFON[locale];
  return (
    <LegalPage page="colofon" locale={locale}>
      <Content />
    </LegalPage>
  );
}
