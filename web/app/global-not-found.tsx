import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = { title: "Not found | OpenFoodAlerts" };

// URLs outside /en and /nl: no locale is known, so the page is bilingual.
export default function GlobalNotFound() {
  return (
    <html lang="en">
      <body>
        <main className="mx-auto max-w-4xl px-4 py-8">
          <h1 className="text-2xl font-semibold">Page not found</h1>
          <p className="mt-2">
            <Link href="/en">Go to OpenFoodAlerts</Link>
          </p>
          <p className="mt-6" lang="nl">
            Pagina niet gevonden. <Link href="/nl">Naar OpenFoodAlerts</Link>
          </p>
        </main>
      </body>
    </html>
  );
}
