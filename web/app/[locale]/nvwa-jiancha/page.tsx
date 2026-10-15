import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { zhGuideMetadata, ZhGuidePage } from "@/components/zh-page";

// Chinese module (spec §9): zh only, static. Text: content/zh/nvwa-jiancha.ts.
export async function generateMetadata({ params }: PageProps<"/[locale]/nvwa-jiancha">): Promise<Metadata> {
  return (await params).locale === "zh" ? zhGuideMetadata("nvwa-jiancha") : {};
}

export default async function Page({ params }: PageProps<"/[locale]/nvwa-jiancha">) {
  if ((await params).locale !== "zh") notFound();
  return <ZhGuidePage slug="nvwa-jiancha" />;
}
