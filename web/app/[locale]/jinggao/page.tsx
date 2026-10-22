import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { loadZhWarnings, zhWarningsMetadata, ZhWarningsView } from "@/components/zh-warnings";

// The Chinese NVWA warning stream (spec §9, ticket 33), page 1: zh only. ISR: static, the
// data cached for an hour (components/zh-warnings.tsx), regenerated in the background.
export const ensureStatic = "navigation";

export async function generateMetadata({ params }: PageProps<"/[locale]/jinggao">): Promise<Metadata> {
  return (await params).locale === "zh" ? zhWarningsMetadata(1) : {};
}

export default async function Page({ params }: PageProps<"/[locale]/jinggao">) {
  if ((await params).locale !== "zh") notFound();
  const data = await loadZhWarnings(1);
  if (!data) notFound();
  return <ZhWarningsView data={data} />;
}
