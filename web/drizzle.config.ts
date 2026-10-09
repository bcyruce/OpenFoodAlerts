// Used only by `make db-types` (drizzle-kit pull): the schema is owned by db/migrations
// (ADR 0001), so TypeScript table definitions are introspected, never written by hand.
import { defineConfig } from "drizzle-kit";

export default defineConfig({
  dialect: "postgresql",
  out: "./db/generated",
  schemaFilter: ["public"],
  // raw_records stays in the generated types because other tables reference it, but the
  // ofa_web role cannot read it (spec §3.1), so web code must not query it.
  tablesFilter: ["!schema_migrations"],
  dbCredentials: {
    url: process.env.DATABASE_URL ?? "postgres://ofa:ofa@localhost:5432/ofa?sslmode=disable",
  },
  introspect: { casing: "camel" },
});
