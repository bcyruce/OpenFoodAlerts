// The test server sends email with EMAIL_TRANSPORT=outbox into this directory
// (playwright.config.ts); tests read the messages back from here.
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

export const OUTBOX_DIR = join(__dirname, ".outbox");

export type OutboxMessage = {
  to: string;
  subject: string;
  text: string;
  html: string;
  tag?: string;
  messageId: string;
};

export function messagesTo(to: string): OutboxMessage[] {
  if (!existsSync(OUTBOX_DIR)) return [];
  return readdirSync(OUTBOX_DIR)
    .filter((f) => f.endsWith(".json"))
    .sort()
    .map((f) => JSON.parse(readFileSync(join(OUTBOX_DIR, f), "utf8")) as OutboxMessage)
    .filter((m) => m.to === to);
}

/** Waits for the first email to `to` (the server sends it after answering the request). */
export async function waitForEmail(to: string, timeoutMs = 20_000): Promise<OutboxMessage> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const [message] = messagesTo(to);
    if (message) return message;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`no email to ${to} in ${OUTBOX_DIR}`);
}

/** A fresh address per test run, so reruns against the same database start clean. */
export function uniqueEmail(label: string): string {
  return `smoke+${label}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@example.com`;
}
