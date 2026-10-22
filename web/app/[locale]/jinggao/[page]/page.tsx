import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { loadZhWarnings, zhWarningsMetadata, ZhWarningsView } from "@/components/zh-warnings";
import { parseZhWarningsPage } from "@/lib/zh-warnings";

// Pages 2… of the Chinese NVWA warning stream (ticket 33): `/zh/jinggao/2`. Path segments
// rather than `?page=`, because server-side searchParams would make every request render
// (no ISR). ISR as for the detail pages: a few pages are prerendered, others render on
// their first request (blocking, so a page past the end is a real 404) and are cached.
export const ensureStatic = "navigation";
// The page reads its params outside <Suspense> on purpose (no fallback shell to stream).
export const instant = false;

const PRERENDERED_PAGES = 5;

// ensureStatic needs at least one parameter set: under en/nl, or with a single page, a
// sentinel that renders as a 404 ("1" is not a valid segment, page 1 is /zh/jinggao).
const SENTINEL = [{ page: "1" }];

export async function generateStaticParams({
  params,
}: {
  params: { locale: string };
}): Promise<{ page: string }[]> {
  if (params.locale !== "zh") return SENTINEL;
  const first = await loadZhWarnings(1);
  const last = Math.min(first?.totalPages ?? 1, PRERENDERED_PAGES);
  const pages = Array.from({ length: Math.max(0, last - 1) }, (_, i) => ({ page: String(i + 2) }));
  return pages.length > 0 ? pages : SENTINEL;
}

async function resolve(params: PageProps<"/[locale]/jinggao/[page]">["params"]) {
  const { locale, page: segment } = await params;
  const page = locale === "zh" ? parseZhWarningsPage(segment) : null;
  return { page, data: page === null ? null : await loadZhWarnings(page) };
}

export async function generateMetadata({ params }: PageProps<"/[locale]/jinggao/[page]">): Promise<Metadata> {
  const { page, data } = await resolve(params);
  return page !== null && data ? zhWarningsMetadata(page) : {};
}

export default async function Page({ params }: PageProps<"/[locale]/jinggao/[page]">) {
  const { data } = await resolve(params);
  if (!data) notFound();
  return <ZhWarningsView data={data} />;
}
