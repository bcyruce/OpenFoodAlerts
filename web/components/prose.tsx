import type { ReactNode } from "react";

/**
 * Typography for long texts (legal pages, the data card): headings, paragraphs, lists,
 * definition lists and tables written as plain HTML elements. Wide tables sit in a
 * `.table-scroll` region.
 */
export const PROSE_CLASSES = [
  "text-slate-800",
  "[&_h2]:mt-10 [&_h2]:text-xl [&_h2]:font-semibold [&_h2]:text-slate-900",
  "[&_h3]:mt-6 [&_h3]:text-lg [&_h3]:font-semibold [&_h3]:text-slate-900",
  "[&_p]:mt-3 [&_blockquote]:mt-4 [&_blockquote]:border-l-4 [&_blockquote]:border-slate-300 [&_blockquote]:pl-4 [&_blockquote]:text-slate-700",
  "[&_ul]:mt-3 [&_ul]:list-disc [&_ul]:pl-6 [&_ol]:mt-3 [&_ol]:list-decimal [&_ol]:pl-6 [&_li]:mt-1",
  "[&_dl]:mt-4 [&_dt]:mt-3 [&_dt]:font-semibold [&_dd]:mt-0.5",
  "[&_code]:rounded [&_code]:bg-slate-100 [&_code]:px-1 [&_code]:text-[0.9em]",
  "[&_.table-scroll]:mt-4 [&_.table-scroll]:max-w-full [&_.table-scroll]:overflow-x-auto",
  "[&_table]:mt-4 [&_table]:w-full [&_table]:border-collapse [&_table]:text-sm",
  "[&_.table-scroll>table]:mt-0",
  "[&_th]:border [&_th]:border-slate-300 [&_th]:bg-slate-50 [&_th]:px-2 [&_th]:py-1 [&_th]:text-left [&_th]:align-top",
  "[&_td]:border [&_td]:border-slate-300 [&_td]:px-2 [&_td]:py-1 [&_td]:align-top",
].join(" ");

export function Prose({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  return <div className={`${PROSE_CLASSES} ${wide ? "" : "max-w-prose"}`}>{children}</div>;
}
