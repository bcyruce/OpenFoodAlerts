import { mkdtempSync, readdirSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  createBrevoTransport,
  createMemoryTransport,
  createOutboxTransport,
  transportFromEnv,
  type EmailMessage,
} from "./transport";

const message: EmailMessage = {
  to: "jan@example.nl",
  subject: "Bevestig uw abonnement",
  text: "Tekst",
  html: "<p>Tekst</p>",
  tag: "confirm",
};

describe("Brevo transport", () => {
  it("posts the message to the transactional email API and returns the message id", async () => {
    const calls: { url: string; init: RequestInit }[] = [];
    const transport = createBrevoTransport({
      apiKey: "xkeysib-test",
      sender: { email: "noreply@openfoodalerts.nl", name: "OpenFoodAlerts" },
      fetch: async (url, init) => {
        calls.push({ url: String(url), init: init! });
        return new Response(JSON.stringify({ messageId: "<abc@smtp-relay.mailin.fr>" }), {
          status: 201,
        });
      },
    });
    const result = await transport.send(message);
    expect(result).toEqual({ messageId: "<abc@smtp-relay.mailin.fr>" });
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe("https://api.brevo.com/v3/smtp/email");
    expect(calls[0].init.method).toBe("POST");
    expect(new Headers(calls[0].init.headers).get("api-key")).toBe("xkeysib-test");
    expect(JSON.parse(String(calls[0].init.body))).toEqual({
      sender: { email: "noreply@openfoodalerts.nl", name: "OpenFoodAlerts" },
      to: [{ email: "jan@example.nl" }],
      subject: "Bevestig uw abonnement",
      textContent: "Tekst",
      htmlContent: "<p>Tekst</p>",
      tags: ["confirm"],
    });
  });

  it("fails on an error response without leaking the API key", async () => {
    const transport = createBrevoTransport({
      apiKey: "xkeysib-secret",
      sender: { email: "noreply@openfoodalerts.nl", name: "OpenFoodAlerts" },
      fetch: async () => new Response('{"code":"unauthorized"}', { status: 401 }),
    });
    const error = await transport.send(message).catch((e: Error) => e);
    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toContain("401");
    expect((error as Error).message).not.toContain("xkeysib-secret");
  });
});

describe("outbox transport", () => {
  it("writes each message as a JSON file", async () => {
    const dir = mkdtempSync(join(tmpdir(), "ofa-outbox-"));
    const transport = createOutboxTransport(dir);
    const { messageId } = await transport.send(message);
    const files = readdirSync(dir);
    expect(files).toHaveLength(1);
    const stored = JSON.parse(readFileSync(join(dir, files[0]), "utf8"));
    expect(stored).toMatchObject({ ...message, messageId });
  });
});

describe("transportFromEnv", () => {
  it("requires Brevo settings when EMAIL_TRANSPORT=brevo", () => {
    expect(() => transportFromEnv({ EMAIL_TRANSPORT: "brevo" })).toThrow(/BREVO_API_KEY/);
    expect(
      transportFromEnv({
        EMAIL_TRANSPORT: "brevo",
        BREVO_API_KEY: "k",
        EMAIL_FROM: "noreply@openfoodalerts.nl",
      }).name,
    ).toBe("brevo");
  });

  it("refuses to run without a transport in production", () => {
    expect(() => transportFromEnv({ NODE_ENV: "production" })).toThrow(/EMAIL_TRANSPORT/);
    expect(transportFromEnv({ NODE_ENV: "development" }).name).toBe("log");
    expect(() => transportFromEnv({ EMAIL_TRANSPORT: "smtp" })).toThrow(/EMAIL_TRANSPORT/);
  });
});

describe("memory transport", () => {
  it("keeps sent messages for tests", async () => {
    const transport = createMemoryTransport();
    await transport.send(message);
    expect(transport.sent).toEqual([message]);
  });
});
