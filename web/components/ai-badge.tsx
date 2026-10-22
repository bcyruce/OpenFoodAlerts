"use client";

import { useId, useState } from "react";

/** sm:w-72 */
const POPUP_WIDTH = 288;

export type AiBadgeProps = {
  reviewed: boolean;
  /** Visible badge text ("AI" / "Reviewed") and the rest of its accessible name. */
  text: string;
  suffix: string;
  /** Who made the value, when, prompt version, test-set accuracy, "the official text prevails". */
  description: string;
  links: { href: string; text: string; hrefLang?: string; external?: boolean }[];
};

/**
 * The AI badge (spec §9): a button whose description is the provenance of the value, also
 * shown as a popup on hover and on keyboard focus (CSS, so it works before hydration and
 * without JavaScript), with links to the official source and the evaluation page. The
 * popup stays open while the pointer is over it and closes with Escape (WCAG 1.4.13).
 */
export function AiBadge({ reviewed, text, suffix, description, links }: AiBadgeProps) {
  const id = useId();
  const [dismissed, setDismissed] = useState(false);
  // From sm up the popup hangs below the badge; near the right edge it opens leftwards.
  const [alignRight, setAlignRight] = useState(false);
  const place = (el: HTMLElement) => {
    setAlignRight(el.getBoundingClientRect().left + POPUP_WIDTH > window.innerWidth - 16);
  };
  return (
    <span
      className="group relative inline-flex"
      data-testid="ai-badge"
      data-reviewed={reviewed ? "true" : "false"}
      onMouseEnter={(e) => place(e.currentTarget)}
      onFocus={(e) => place(e.currentTarget)}
      onMouseLeave={() => setDismissed(false)}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDismissed(false);
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape") setDismissed(true);
      }}
    >
      <button
        type="button"
        aria-describedby={`${id}-description`}
        className={`rounded px-1 text-xs font-semibold leading-5 text-white ${
          reviewed ? "bg-emerald-800" : "bg-violet-800"
        }`}
      >
        {reviewed && <span aria-hidden="true">✓ </span>}
        {text}
        {suffix && <span className="sr-only">{suffix}</span>}
      </button>
      <span
        data-testid="ai-badge-popup"
        // Phones: a sheet at the bottom of the screen, so it never widens the page.
        className={`fixed inset-x-4 bottom-4 z-50 sm:absolute sm:inset-x-auto sm:bottom-auto sm:top-full sm:z-20 sm:w-72 sm:pt-1 ${
          alignRight ? "sm:right-0" : "sm:left-0"
        } ${dismissed ? "hidden" : "hidden group-focus-within:block group-hover:block"}`}
      >
        <span className="block rounded-md border border-slate-400 bg-white p-3 text-left text-sm font-normal text-slate-900 shadow-lg">
          <span id={`${id}-description`} className="block">
            {description}
          </span>
          <span className="mt-2 flex flex-col gap-1">
            {links.map((l) => (
              <a
                key={l.href}
                href={l.href}
                hrefLang={l.hrefLang}
                rel={l.external ? "external noopener" : undefined}
              >
                {l.text}
              </a>
            ))}
          </span>
        </span>
      </span>
    </span>
  );
}

/** The plain AI marker for aggregate numbers (dashboard), where no single model applies. */
export function AiMark({ label }: { label: string }) {
  return (
    <span
      data-testid="ai-mark"
      className="ml-1 inline-block rounded border border-dashed border-violet-700 px-1 text-xs font-semibold text-violet-900"
    >
      AI<span className="sr-only"> ({label})</span>
    </span>
  );
}
