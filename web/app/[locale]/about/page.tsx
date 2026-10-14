import type { Metadata } from "next";
import { LegalPage, legalMetadata } from "@/components/legal-page";
import { ABOUT } from "@/content/legal/about";
import type { Locale } from "@/i18n/routing";

// Static (spec §9), en/nl/zh. No SnelVink box here (spec §11.3 rule 3), only a text link.
export const ensureStatic = "navigation";

export async function generateMetadata({ params }: PageProps<"/[locale]/about">): Promise<Metadata> {
  return legalMetadata("about", (await params).locale as Locale);
}

export default async function AboutPage({ params }: PageProps<"/[locale]/about">) {
  const locale = (await params).locale as Locale;
  const Content = ABOUT[locale];
  return (
    <LegalPage page="about" locale={locale}>
      <Content />
    </LegalPage>
  );
}
