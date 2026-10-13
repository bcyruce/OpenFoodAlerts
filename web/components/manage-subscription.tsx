"use client";

import { useFormatter, useTranslations } from "next-intl";
import { useId, useRef, useState, type FormEvent, type RefObject } from "react";
import { SubscriptionSettingsFields, useSubscriptionSettings } from "@/components/subscription-settings";
import type { LocalizedCatalog } from "@/lib/subscriptions/catalog";
import type { ManagedSubscription, SubscriptionStatus } from "@/lib/subscriptions/manage";

type Props = {
  token: string;
  subscription: ManagedSubscription;
  catalog: LocalizedCatalog;
  formPath: string;
};

type Message = { kind: "ok" | "error"; text: string } | null;

const BUTTON =
  "rounded px-5 py-2 font-semibold text-white disabled:opacity-70 bg-blue-700 hover:bg-blue-900";
const DANGER_BUTTON =
  "rounded px-5 py-2 font-semibold text-white disabled:opacity-70 bg-red-800 hover:bg-red-900";

function Notice({ message }: { message: Message }) {
  if (!message) return null;
  return message.kind === "ok" ? (
    <p className="rounded border border-green-700 bg-green-50 p-3 font-medium">{message.text}</p>
  ) : (
    <p className="rounded border border-red-800 bg-red-50 p-3 font-medium text-red-900">{message.text}</p>
  );
}

async function postJson(path: string, body: object): Promise<number> {
  try {
    const response = await fetch(path, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    return response.status;
  } catch {
    return 0;
  }
}

/** The manage page (spec §9 `/alerts/manage/[token]`): edit, unsubscribe, delete my data. */
export function ManageSubscription({ token, subscription, catalog, formPath }: Props) {
  const t = useTranslations("Manage");
  const format = useFormatter();
  const ids = useId();
  const settings = useSubscriptionSettings(subscription);
  const [status, setStatus] = useState<SubscriptionStatus>(subscription.status);
  const [unsubscribedAt, setUnsubscribedAt] = useState(subscription.unsubscribedAt);
  const [busy, setBusy] = useState<"save" | "unsubscribe" | "delete" | null>(null);
  const [invalid, setInvalid] = useState<Set<string>>(new Set());
  const [saveMessage, setSaveMessage] = useState<Message>(null);
  const [unsubscribeMessage, setUnsubscribeMessage] = useState<Message>(null);
  const [deleteMessage, setDeleteMessage] = useState<Message>(null);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deleted, setDeleted] = useState(false);
  const saveRef = useRef<HTMLDivElement>(null);
  const unsubscribeRef = useRef<HTMLDivElement>(null);
  const deletedRef = useRef<HTMLHeadingElement>(null);

  const problem = (code: number) =>
    code === 429
      ? t("errorRateLimited")
      : code === 404
        ? t("errorGone")
        : code === 409
          ? t("errorUnsubscribed")
          : code === 400
            ? t("errorInvalid")
            : t("errorServer");
  const focus = (ref: RefObject<HTMLElement | null>) => requestAnimationFrame(() => ref.current?.focus());

  async function save(event: FormEvent) {
    event.preventDefault();
    if (settings.effectiveSources.length === 0) {
      setInvalid(new Set(["filters.sources"]));
      setSaveMessage({ kind: "error", text: t("errorInvalid") });
      return focus(saveRef);
    }
    setInvalid(new Set());
    setBusy("save");
    const code = await postJson("/api/manage", { token, ...settings.body() });
    setBusy(null);
    setSaveMessage(code === 200 ? { kind: "ok", text: t("saved") } : { kind: "error", text: problem(code) });
    focus(saveRef);
  }

  async function unsubscribeNow() {
    setBusy("unsubscribe");
    const code = await postJson("/api/unsubscribe", { token });
    setBusy(null);
    if (code === 200) {
      setStatus("unsubscribed");
      setUnsubscribedAt(new Date().toISOString());
      setUnsubscribeMessage({ kind: "ok", text: t("unsubscribed") });
    } else {
      setUnsubscribeMessage({ kind: "error", text: problem(code) });
    }
    focus(unsubscribeRef);
  }

  async function deleteData() {
    setBusy("delete");
    const code = await postJson("/api/delete", { token });
    setBusy(null);
    if (code === 200) {
      setDeleted(true);
      focus(deletedRef);
    } else {
      setDeleteMessage({ kind: "error", text: problem(code) });
    }
  }

  if (deleted) {
    return (
      <div role="status" className="mt-6 rounded border border-green-700 bg-green-50 p-4">
        <h2 ref={deletedRef} tabIndex={-1} className="text-lg font-semibold">
          {t("deletedHeading")}
        </h2>
        <p className="mt-2">{t("deleted")}</p>
      </div>
    );
  }

  const live = status !== "unsubscribed";
  const date = unsubscribedAt ? format.dateTime(new Date(unsubscribedAt), { dateStyle: "long" }) : "";

  return (
    <div className="mt-4 space-y-10">
      <div className="space-y-2">
        <p>{t("forAddress", { email: subscription.maskedEmail })}</p>
        <p className="font-medium" data-testid="subscription-status">
          {status === "unsubscribed" ? t("statusUnsubscribed", { date }) : t(`status.${status}`)}
        </p>
      </div>

      {live && (
        <section aria-labelledby={`${ids}-settings`}>
          <h2 id={`${ids}-settings`} className="text-xl font-semibold">
            {t("settingsHeading")}
          </h2>
          <p className="mt-1 text-sm text-slate-700">{t("emailNote")}</p>
          <form onSubmit={save} noValidate className="mt-4 space-y-6" data-testid="manage-form">
            <SubscriptionSettingsFields settings={settings} catalog={catalog} ids={ids} invalid={invalid} />
            <div ref={saveRef} tabIndex={-1} aria-live="polite" className="outline-none">
              <Notice message={saveMessage} />
            </div>
            <button type="submit" disabled={busy !== null} className={BUTTON}>
              {busy === "save" ? t("saving") : t("save")}
            </button>
          </form>
        </section>
      )}

      <section
        id="unsubscribe"
        aria-labelledby={`${ids}-unsubscribe`}
        className="rounded border border-slate-300 p-4 target:border-blue-700 target:ring-2 target:ring-blue-700"
      >
        <h2 id={`${ids}-unsubscribe`} className="text-xl font-semibold">
          {t("unsubscribeHeading")}
        </h2>
        <div ref={unsubscribeRef} tabIndex={-1} aria-live="polite" className="mt-2 outline-none">
          <Notice message={unsubscribeMessage} />
        </div>
        {live ? (
          <>
            <p className="mt-2">{t("unsubscribeIntro")}</p>
            <button type="button" onClick={unsubscribeNow} disabled={busy !== null} className={`${BUTTON} mt-4`}>
              {busy === "unsubscribe" ? t("unsubscribing") : t("unsubscribeButton")}
            </button>
          </>
        ) : (
          !unsubscribeMessage && <p className="mt-2">{t("alreadyUnsubscribed")}</p>
        )}
        {!live && (
          <p className="mt-2">
            <a href={formPath}>{t("subscribeAgain")}</a>
          </p>
        )}
      </section>

      <section aria-labelledby={`${ids}-delete`} className="rounded border border-slate-300 p-4">
        <h2 id={`${ids}-delete`} className="text-xl font-semibold">
          {t("deleteHeading")}
        </h2>
        <p className="mt-2">{t("deleteIntro")}</p>
        <div aria-live="polite" className="mt-2">
          <Notice message={deleteMessage} />
          {confirmingDelete && <p className="font-medium">{t("deleteConfirm")}</p>}
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          {confirmingDelete ? (
            <>
              <button type="button" onClick={deleteData} disabled={busy !== null} className={DANGER_BUTTON}>
                {busy === "delete" ? t("deleting") : t("deleteConfirmButton")}
              </button>
              <button
                type="button"
                onClick={() => setConfirmingDelete(false)}
                disabled={busy !== null}
                className="rounded border border-slate-500 px-5 py-2 font-semibold"
              >
                {t("deleteCancel")}
              </button>
            </>
          ) : (
            <button type="button" onClick={() => setConfirmingDelete(true)} className={DANGER_BUTTON}>
              {t("deleteButton")}
            </button>
          )}
        </div>
      </section>
    </div>
  );
}
