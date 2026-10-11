"use client";

import { useTranslations } from "next-intl";
import { useRef, useState, useSyncExternalStore } from "react";

type State = "ready" | "confirming" | "confirmed" | "invalid" | "expired" | "rate_limited" | "error";

function subscribe(onChange: () => void) {
  window.addEventListener("hashchange", onChange);
  return () => window.removeEventListener("hashchange", onChange);
}

/** The token from `#token=…`; null while rendering on the server. */
function useHashToken(): string | null | undefined {
  return useSyncExternalStore(
    subscribe,
    () => new URLSearchParams(window.location.hash.slice(1)).get("token"),
    () => undefined,
  );
}

/** Confirms a Subscription with the token from the link, after an explicit click. */
export function ConfirmSubscription({ formPath }: { formPath: string }) {
  const t = useTranslations("AlertsConfirm");
  const hashToken = useHashToken();
  // Kept after the fragment is removed from the address bar.
  const [token, setToken] = useState<string | null>(null);
  const [state, setState] = useState<State>("ready");
  const resultRef = useRef<HTMLDivElement>(null);
  const current = token ?? hashToken;

  async function confirm() {
    if (!current) return;
    setToken(current);
    setState("confirming");
    let next: State = "error";
    try {
      const response = await fetch("/api/confirm", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ token: current }),
      });
      next =
        response.status === 200
          ? "confirmed"
          : response.status === 410
            ? "expired"
            : response.status === 400
              ? "invalid"
              : response.status === 429
                ? "rate_limited"
                : "error";
    } catch {
      next = "error";
    }
    // The token is used up (or useless); drop it from the address bar and history.
    if (next !== "rate_limited" && next !== "error") {
      window.history.replaceState(null, "", window.location.pathname);
    }
    setState(next);
    requestAnimationFrame(() => resultRef.current?.focus());
  }

  if (current === undefined) return null;

  if (state === "confirmed") {
    return (
      <div ref={resultRef} tabIndex={-1} role="status" className="mt-6 rounded border border-green-700 bg-green-50 p-4">
        <h2 className="text-lg font-semibold">{t("successHeading")}</h2>
        <p className="mt-2">{t("success")}</p>
      </div>
    );
  }

  const problem =
    current === null && state === "ready"
      ? "missing"
      : state === "invalid" || state === "expired" || state === "error"
        ? state
        : state === "rate_limited"
          ? "rateLimited"
          : null;

  return (
    <div className="mt-4 space-y-4">
      <div ref={resultRef} tabIndex={-1} aria-live="polite" className="outline-none">
        {problem && (
          <p className="rounded border border-red-800 bg-red-50 p-3 font-medium text-red-900">{t(problem)}</p>
        )}
      </div>
      {current && (state === "ready" || state === "confirming" || state === "rate_limited" || state === "error") ? (
        <>
          <p className="text-slate-700">{t("intro")}</p>
          <button
            type="button"
            onClick={confirm}
            disabled={state === "confirming"}
            className="rounded bg-blue-700 px-5 py-2 font-semibold text-white hover:bg-blue-900 disabled:opacity-70"
          >
            {state === "confirming" ? t("confirming") : t("button")}
          </button>
        </>
      ) : (
        <p>
          <a href={formPath}>{t("subscribeAgain")}</a>
        </p>
      )}
    </div>
  );
}
