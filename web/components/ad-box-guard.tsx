"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { isAdBoxAllowed } from "@/lib/ad-box";

/**
 * Renders the ad box only where spec §11.3 rule 3 allows it, judged by the real pathname
 * rather than by what the page says about itself.
 */
export function AdBoxGuard({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "";
  if (!isAdBoxAllowed(pathname)) {
    if (process.env.NODE_ENV !== "production") {
      console.error(`<AdBox> is not allowed on ${pathname} (spec §11.3); nothing rendered.`);
    }
    return null;
  }
  return children;
}
