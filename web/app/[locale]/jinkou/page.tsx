import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { zhGuideMetadata, ZhGuidePage } from "@/components/zh-page";

// Chinese module (spec §9): zh only, static. Text: content/zh/jinkou.ts.
export async function generateMetadata({ params }: PageProps<"/[locale]/jinkou">): Promise<Metadata> {
  return (await params).locale === "zh" ? zhGuideMetadata("jinkou") : {};
}

export default async function Page({ params }: PageProps<"/[locale]/jinkou">) {
  if ((await params).locale !== "zh") notFound();
  return <ZhGuidePage slug="jinkou" />;
}
