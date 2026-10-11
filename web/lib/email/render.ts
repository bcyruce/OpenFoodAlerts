/**
 * Email template framework (spec §10.5): a template lists content blocks once and gets a
 * plain-text and an HTML version that say the same thing. HTML is escaped here, so
 * templates pass plain strings. No images, tracking pixels or promotional content.
 */
import { HTML_LANG } from "@/i18n/routing";
import type { SubscriptionLocale } from "@/lib/subscriptions/validate";

export type EmailBlock =
  | { kind: "paragraph"; text: string }
  | { kind: "list"; items: string[] }
  | { kind: "button"; label: string; url: string }
  | { kind: "note"; text: string };

export type EmailContent = {
  locale: SubscriptionLocale;
  subject: string;
  blocks: EmailBlock[];
  /** Short lines under a separator, e.g. who sends the email and why. */
  footer: string[];
};

export type RenderedEmail = { subject: string; text: string; html: string };

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function blockText(block: EmailBlock): string {
  switch (block.kind) {
    case "paragraph":
    case "note":
      return block.text;
    case "list":
      return block.items.map((item) => `- ${item}`).join("\n");
    case "button":
      return `${block.label}:\n${block.url}`;
  }
}

const TEXT_COLOR = "#0f172a";
const MUTED_COLOR = "#475569";
const LINK_COLOR = "#1d4ed8";

function blockHtml(block: EmailBlock): string {
  switch (block.kind) {
    case "paragraph":
      return `<p style="margin:0 0 16px">${escapeHtml(block.text)}</p>`;
    case "note":
      return `<p style="margin:0 0 16px;font-size:14px;color:${MUTED_COLOR}">${escapeHtml(block.text)}</p>`;
    case "list":
      return `<ul style="margin:0 0 16px;padding-left:20px">${block.items
        .map((item) => `<li>${escapeHtml(item)}</li>`)
        .join("")}</ul>`;
    case "button":
      return (
        `<p style="margin:24px 0"><a href="${escapeHtml(block.url)}" ` +
        `style="display:inline-block;background:${LINK_COLOR};color:#ffffff;padding:12px 20px;` +
        `border-radius:6px;text-decoration:none;font-weight:600">${escapeHtml(block.label)}</a></p>` +
        `<p style="margin:0 0 16px;font-size:14px;color:${MUTED_COLOR};word-break:break-all">` +
        `<a href="${escapeHtml(block.url)}" style="color:${LINK_COLOR}">${escapeHtml(block.url)}</a></p>`
      );
  }
}

export function renderEmail(content: EmailContent): RenderedEmail {
  const parts = content.blocks.map(blockText);
  if (content.footer.length > 0) parts.push(`--\n${content.footer.join("\n")}`);
  const text = `${parts.join("\n\n")}\n`;

  const footer = content.footer
    .map((line) => `<p style="margin:0 0 4px">${escapeHtml(line)}</p>`)
    .join("");
  const html =
    `<!doctype html>\n<html lang="${HTML_LANG[content.locale]}">` +
    `<head><meta charset="utf-8"><meta name="viewport" content="width=device-width">` +
    `<title>${escapeHtml(content.subject)}</title></head>` +
    `<body style="margin:0;padding:24px;background:#ffffff;color:${TEXT_COLOR};` +
    `font-family:system-ui,-apple-system,'Segoe UI',Roboto,'PingFang SC','Microsoft YaHei',sans-serif;` +
    `font-size:16px;line-height:1.5">` +
    `<div style="max-width:560px;margin:0 auto">` +
    content.blocks.map(blockHtml).join("") +
    (footer
      ? `<hr style="border:none;border-top:1px solid #cbd5e1;margin:24px 0">` +
        `<div style="font-size:13px;color:${MUTED_COLOR}">${footer}</div>`
      : "") +
    `</div></body></html>\n`;

  return { subject: content.subject, text, html };
}
