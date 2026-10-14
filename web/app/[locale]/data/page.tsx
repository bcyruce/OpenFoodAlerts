import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Prose } from "@/components/prose";
import { loadDataCard } from "@/lib/data-card";
import { repoFileUrl } from "@/lib/repo";
import { loadTaxonomy, type Taxonomy } from "@/lib/taxonomy";

// Static and English only (spec §9); /nl/data and /zh/data redirect here (next.config.ts).
// The content is docs/data_card.md and db/seed/taxonomy/, read at build time.
export const ensureStatic = "navigation";

const TITLE = "Data and methods";

export async function generateMetadata({ params }: PageProps<"/[locale]/data">): Promise<Metadata> {
  if ((await params).locale !== "en") return {};
  return {
    title: TITLE,
    description:
      "Sources, licences and attribution, coverage, fields, methods, exclusion rules and the taxonomy merge table of OpenFoodAlerts.",
    alternates: { canonical: "/en/data", languages: { en: "/en/data" } },
  };
}

function TaxonomyTable({ taxonomy }: { taxonomy: Taxonomy }) {
  const status = taxonomy.frozen ? "frozen" : "draft — not frozen";
  return (
    <section aria-labelledby="taxonomy-table-heading" className="mt-6">
      <h3 id="taxonomy-table-heading">Merge table</h3>
      <p data-testid="taxonomy-status">
        <strong>Taxonomy v{taxonomy.version}: {status}.</strong>{" "}
        {taxonomy.frozen
          ? "Changes only through a new taxonomy version."
          : "This draft can still change until the domain expert freezes it (ticket 11)."}{" "}
        {taxonomy.categories.length} RASFF Hazard categories map to {taxonomy.labels.length} T1
        labels. Source: <a href={repoFileUrl(taxonomy.file)}>{taxonomy.file}</a>.
      </p>
      <div
        className="table-scroll"
        tabIndex={0}
        role="region"
        aria-label="Taxonomy merge table"
      >
        <table data-testid="taxonomy-table">
          <caption className="sr-only">
            Taxonomy v{taxonomy.version} ({status}): RASFF Hazard categories and the T1 label each
            maps to, with RASFF Notifications since 2020-01-01
          </caption>
          <thead>
            <tr>
              <th scope="col">T1 label</th>
              <th scope="col">RASFF Hazard category</th>
              <th scope="col">RASFF id</th>
              <th scope="col" className="text-right">
                Notifications since 2020
              </th>
            </tr>
          </thead>
          {taxonomy.labels.map((group) => (
            <tbody key={group.label}>
              {group.categories.map((category, i) => (
                <tr key={category.rasffId}>
                  {i === 0 ? (
                    <th scope="rowgroup" rowSpan={group.categories.length}>
                      {group.label}
                      {group.categories.length > 1 ? (
                        <span className="block font-normal text-slate-700">
                          {group.categories.length} categories, {group.count.toLocaleString("en-GB")}
                        </span>
                      ) : null}
                    </th>
                  ) : null}
                  <td>{category.name}</td>
                  <td>{category.rasffId}</td>
                  <td className="text-right tabular-nums">{category.count.toLocaleString("en-GB")}</td>
                </tr>
              ))}
            </tbody>
          ))}
        </table>
      </div>
    </section>
  );
}

export default async function DataPage({ params }: PageProps<"/[locale]/data">) {
  if ((await params).locale !== "en") notFound();
  const card = loadDataCard();
  const taxonomy = loadTaxonomy();
  return (
    <article>
      <h1 className="text-3xl font-semibold text-slate-900">{TITLE}</h1>
      <p className="mt-2 max-w-prose text-slate-700">
        Where the data come from, under which licence, what the fields mean and how
        OpenFoodAlerts processes them. This page is the data card of the project; its text is{" "}
        <a href={repoFileUrl("docs/data_card.md")}>docs/data_card.md</a> in the repository.
      </p>
      <Prose wide>
        <div dangerouslySetInnerHTML={{ __html: card.before }} />
        <TaxonomyTable taxonomy={taxonomy} />
        <div dangerouslySetInnerHTML={{ __html: card.after }} />
      </Prose>
    </article>
  );
}
