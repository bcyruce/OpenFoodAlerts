/**
 * Sending email (spec §10). The app talks to an `EmailTransport`; `EMAIL_TRANSPORT`
 * picks the implementation:
 *
 * - `brevo`: Brevo transactional API (production). Needs BREVO_API_KEY and EMAIL_FROM
 *   (EMAIL_FROM_NAME defaults to "OpenFoodAlerts").
 * - `outbox`: writes each message as JSON into EMAIL_OUTBOX_DIR (Playwright reads it).
 * - `log`: prints the message to stdout (local development; the default outside
 *   production). Never use it in production: the log would contain addresses and tokens.
 */
import { randomUUID } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

export type EmailMessage = {
  to: string;
  subject: string;
  text: string;
  html: string;
  /** Extra headers, e.g. List-Unsubscribe for Digest and Instant emails. */
  headers?: Record<string, string>;
  /** Kind of email, for the provider's statistics (`confirm`, `digest`, `instant`). */
  tag?: string;
};

export type SendResult = { messageId: string | null };

export interface EmailTransport {
  readonly name: string;
  send(message: EmailMessage): Promise<SendResult>;
}

const BREVO_URL = "https://api.brevo.com/v3/smtp/email";

export function createBrevoTransport(options: {
  apiKey: string;
  sender: { email: string; name: string };
  fetch?: typeof fetch;
}): EmailTransport {
  const doFetch = options.fetch ?? fetch;
  return {
    name: "brevo",
    async send(message) {
      const response = await doFetch(BREVO_URL, {
        method: "POST",
        headers: {
          "api-key": options.apiKey,
          "content-type": "application/json",
          accept: "application/json",
        },
        body: JSON.stringify({
          sender: options.sender,
          to: [{ email: message.to }],
          subject: message.subject,
          textContent: message.text,
          htmlContent: message.html,
          ...(message.headers ? { headers: message.headers } : {}),
          ...(message.tag ? { tags: [message.tag] } : {}),
        }),
        signal: AbortSignal.timeout(15_000),
      });
      if (!response.ok) {
        const detail = (await response.text()).slice(0, 300);
        throw new Error(`Brevo responded ${response.status}: ${detail}`);
      }
      const body = (await response.json()) as { messageId?: string };
      return { messageId: body.messageId ?? null };
    },
  };
}

export function createOutboxTransport(dir: string): EmailTransport {
  return {
    name: "outbox",
    async send(message) {
      mkdirSync(dir, { recursive: true });
      const messageId = `outbox-${randomUUID()}`;
      const file = join(dir, `${Date.now()}-${messageId}.json`);
      writeFileSync(file, JSON.stringify({ ...message, messageId }, null, 2), "utf8");
      return { messageId };
    },
  };
}

export function createLogTransport(): EmailTransport {
  return {
    name: "log",
    async send(message) {
      console.log(
        `[email:log] to=${message.to} subject=${JSON.stringify(message.subject)}\n${message.text}`,
      );
      return { messageId: null };
    },
  };
}

/** Test double: keeps every message in `sent`. */
export function createMemoryTransport(): EmailTransport & { sent: EmailMessage[] } {
  const sent: EmailMessage[] = [];
  return {
    name: "memory",
    sent,
    async send(message) {
      sent.push(message);
      return { messageId: `memory-${sent.length}` };
    },
  };
}

type Env = Record<string, string | undefined>;

function required(env: Env, name: string): string {
  const value = env[name];
  if (!value) throw new Error(`${name} is not set (needed for EMAIL_TRANSPORT=${env.EMAIL_TRANSPORT})`);
  return value;
}

export function transportFromEnv(env: Env = process.env): EmailTransport {
  const kind = env.EMAIL_TRANSPORT ?? (env.NODE_ENV === "production" ? undefined : "log");
  switch (kind) {
    case "brevo":
      return createBrevoTransport({
        apiKey: required(env, "BREVO_API_KEY"),
        sender: { email: required(env, "EMAIL_FROM"), name: env.EMAIL_FROM_NAME ?? "OpenFoodAlerts" },
      });
    case "outbox":
      return createOutboxTransport(required(env, "EMAIL_OUTBOX_DIR"));
    case "log":
      return createLogTransport();
    default:
      throw new Error(`EMAIL_TRANSPORT must be brevo, outbox or log (got ${kind ?? "nothing"})`);
  }
}
