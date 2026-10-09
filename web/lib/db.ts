import { drizzle } from "drizzle-orm/postgres-js";
import postgres from "postgres";
import type { Reader } from "./notifications";

// The website connects as the read-only `ofa_web` role (spec §11.2) through
// WEB_DATABASE_URL; see `make db-roles`.
let db: Reader | undefined;

export function getDb(): Reader {
  if (!db) {
    const url = process.env.WEB_DATABASE_URL;
    if (!url) throw new Error("WEB_DATABASE_URL is not set");
    db = drizzle(postgres(url, { max: 5, idle_timeout: 30, onnotice: () => {} }));
  }
  return db;
}
