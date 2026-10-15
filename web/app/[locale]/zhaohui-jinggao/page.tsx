import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { zhGuideMetadata, ZhGuidePage } from "@/components/zh-page";

// Chinese module (spec §9): zh only, static. Text: content/zh/zhaohui-jinggao.ts.
export async function generateMetadata({ params }: PageProps<"/[locale]/zhaohui-jinggao">): Promise<Metadata> {
  return (await params).locale === "zh" ? zhGuideMetadata("zhaohui-jinggao") : {};
}

export default async function Page({ params }: PageProps<"/[locale]/zhaohui-jinggao">) {
  if ((await params).locale !== "zh") notFound();
  return <ZhGuidePage slug="zhaohui-jinggao" />;
}
