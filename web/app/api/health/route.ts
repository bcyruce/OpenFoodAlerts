// GET /api/health (spec §8, §13): Source freshness, contract probes and RASFF silence.
// 200 when every Source is healthy, 503 otherwise (also when the database is unreachable).
import { connection } from "next/server";
import { getDb } from "@/lib/db";
import { getHealth, healthStatusCode } from "@/lib/health";

const NO_STORE = { "Cache-Control": "no-store" };

export async function GET(): Promise<Response> {
  // Always computed at request time: never prerendered or cached (Cache Components).
  await connection();
  const now = new Date();
  try {
    const health = await getHealth(getDb(), now);
    return Response.json(health, { status: healthStatusCode(health), headers: NO_STORE });
  } catch (error) {
    console.error("health check failed", error);
    return Response.json(
      { status: "error", checkedAt: now.toISOString(), error: "database unavailable" },
      { status: 503, headers: NO_STORE },
    );
  }
}
