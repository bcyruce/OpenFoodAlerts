/**
 * `docs/data_card.md` is the source of truth for the data card; `/data` renders it at
 * build time. The Markdown is written for readers on GitHub, so links are rewritten for
 * the site: repository paths go to the public repository, `https://openfoodalerts.nl/…`
 * becomes a site path. The taxonomy table is not in the Markdown (it comes from the CSV,
 * `lib/taxonomy.ts`); the page puts it where the marker comment is.
 *
 * The Markdown is our own repository content, so the HTML is not sanitised.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { Marked, Renderer, type Token, type Tokens } from "marked";
import { REPO_ROOT, repoFileUrl } from "./repo";

export const DATA_CARD_FILE = "docs/data_card.md";
export const TAXONOMY_MARKER = "<!-- taxonomy-table -->";

/** The public site origin used in the Markdown's absolute links. */
const SITE_ORIGIN = "https://openfoodalerts.nl";

export type DataCard = {
  /** HTML before the taxonomy table. */
  before: string;
  /** HTML after the taxonomy table. */
  after: string;
};

export function headingId(text: string): string {
  return text
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^\p{L}\p{N}]+/gu, "-")
    .replace(/^-+|-+$/g, "");
}

function rewriteHref(href: string, fromDir: string): string {
  if (href.startsWith("#")) return href;
  if (href === SITE_ORIGIN || href.startsWith(`${SITE_ORIGIN}/`)) {
    return href.slice(SITE_ORIGIN.length) || "/";
  }
  if (/^[a-z][a-z0-9+.-]*:/i.test(href)) return href;
  const [file, hash] = href.split("#");
  const resolved = path.posix.normalize(path.posix.join(fromDir, file));
  return repoFileUrl(resolved) + (hash ? `#${hash}` : "");
}

// Overrides for marked's renderer; `this` is marked's Renderer (with its parser).
const renderer = {
  heading(this: Renderer, { tokens, depth }: Tokens.Heading): string {
    const html = this.parser.parseInline(tokens);
    const plain = this.parser.parseInline(tokens, this.parser.textRenderer);
    return `<h${depth} id="${headingId(plain)}">${html}</h${depth}>\n`;
  },

  // Wide tables scroll inside their own region, which keyboard users can focus.
  table(this: Renderer, token: Tokens.Table): string {
    const columns = token.header
      .map((cell) => this.parser.parseInline(cell.tokens, this.parser.textRenderer))
      .join(", ");
    const label = `Table: ${columns}`.replace(/"/g, "&quot;");
    const table = Renderer.prototype.table.call(this, token);
    return `<div class="table-scroll" tabindex="0" role="region" aria-label="${label}">${table}</div>\n`;
  },
};

export function renderDataCard(markdown: string, file: string = DATA_CARD_FILE): DataCard {
  const marked = new Marked({ gfm: true, renderer });
  const fromDir = path.posix.dirname(file);
  // The page has its own title.
  const tokens = marked.lexer(markdown).filter((t) => !(t.type === "heading" && t.depth === 1));
  marked.walkTokens(tokens, (token) => {
    if (token.type === "link") token.href = rewriteHref(token.href, fromDir);
  });
  const at = tokens.findIndex((t) => t.type === "html" && t.raw.trim() === TAXONOMY_MARKER);
  if (at < 0) throw new Error(`${file}: missing the ${TAXONOMY_MARKER} marker`);
  const render = (part: Token[]) => marked.parser(part);
  return { before: render(tokens.slice(0, at)), after: render(tokens.slice(at + 1)) };
}

export function loadDataCard(): DataCard {
  return renderDataCard(readFileSync(path.join(REPO_ROOT, DATA_CARD_FILE), "utf8"));
}
