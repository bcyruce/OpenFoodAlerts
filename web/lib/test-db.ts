// Test-only helpers for integration tests against TEST_DATABASE_URL (migrated and seeded
// by `make test-db`). Every test runs inside a transaction that is rolled back.
import { sql } from "drizzle-orm";
import { drizzle } from "drizzle-orm/postgres-js";
import postgres from "postgres";

export const testClient = postgres(
  process.env.TEST_DATABASE_URL ?? "postgres://ofa:ofa@localhost:5432/ofa_test?sslmode=disable",
  { max: 1, onnotice: () => {} },
);
export const testDb = drizzle(testClient);

export type Tx = Parameters<Parameters<typeof testDb.transaction>[0]>[0];

class Rollback extends Error {}

/** Runs `fn` in a transaction that is always rolled back, optionally as another role. */
export async function withRollback(
  fn: (tx: Tx) => Promise<void>,
  options: { role?: "ofa_web" | "ofa_pipeline" | "ofa_mailer" } = {},
): Promise<void> {
  try {
    await testDb.transaction(async (tx) => {
      if (options.role) await tx.execute(sql.raw(`SET LOCAL ROLE ${options.role}`));
      await fn(tx);
      throw new Rollback();
    });
  } catch (e) {
    if (!(e instanceof Rollback)) throw e;
  }
}

/**
 * Runs `fn` in a savepoint and returns the Postgres error code it failed with (e.g. 42501
 * insufficient_privilege), or null if it succeeded. The outer transaction stays usable.
 */
export async function pgErrorCode(tx: Tx, fn: (sp: Tx) => Promise<unknown>): Promise<string | null> {
  try {
    await tx.transaction(async (sp) => {
      await fn(sp);
    });
    return null;
  } catch (e) {
    const err = e as { code?: string; cause?: { code?: string } };
    return err.cause?.code ?? err.code ?? "unknown";
  }
}
