import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { zhGuideMetadata, ZhGuidePage } from "@/components/zh-page";

// Chinese module (spec §9): zh only, static. Text: content/zh/jiancha-jieguo-gongkai.ts.
export async function generateMetadata({
  params,
}: PageProps<"/[locale]/jiancha-jieguo-gongkai">): Promise<Metadata> {
  return (await params).locale === "zh" ? zhGuideMetadata("jiancha-jieguo-gongkai") : {};
}

export default async function Page({ params }: PageProps<"/[locale]/jiancha-jieguo-gongkai">) {
  if ((await params).locale !== "zh") notFound();
  return <ZhGuidePage slug="jiancha-jieguo-gongkai" />;
}
