/**
 * Tokens and hashes for Subscriptions (spec §11.1 #2, #3, #5). Only hashes reach the
 * database. These formats are a contract with the Python mailer (tickets 30, 31), which
 * must build the same manage token and email hash:
 *
 * - confirm token: 32 random bytes, base64url (43 chars); stored as `tokenHash`.
 * - manage token: base64url(HMAC-SHA256(OFA_TOKEN_SECRET, "manage:v1:" + subscription id));
 *   stored as `tokenHash`. Derived rather than random so Digest/Instant emails can carry
 *   manage and unsubscribe links without the token ever being stored.
 * - tokenHash: lowercase hex SHA-256 of the token's UTF-8 bytes.
 * - emailHash: hex HMAC-SHA256(OFA_HASH_PEPPER, "email:v1:" + normalized email).
 * - ipHash: hex HMAC-SHA256(OFA_HASH_PEPPER, "ip:v1:" + IP address as received).
 */
import { createHash, createHmac, randomBytes } from "node:crypto";
import { normalizeEmail } from "./validate";

export function newConfirmToken(): string {
  return randomBytes(32).toString("base64url");
}

export function tokenHash(token: string): string {
  return createHash("sha256").update(token, "utf8").digest("hex");
}

export function manageToken(subscriptionId: string, tokenSecret: string): string {
  return createHmac("sha256", tokenSecret).update(`manage:v1:${subscriptionId}`).digest("base64url");
}

export function emailHash(email: string, pepper: string): string {
  return createHmac("sha256", pepper).update(`email:v1:${normalizeEmail(email)}`).digest("hex");
}

export function ipHash(ip: string, pepper: string): string {
  return createHmac("sha256", pepper).update(`ip:v1:${ip}`).digest("hex");
}

/** Tokens as they appear in links: base64url of 32 bytes. */
export const TOKEN_PATTERN = /^[A-Za-z0-9_-]{43}$/;
