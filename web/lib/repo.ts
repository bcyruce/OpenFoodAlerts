/** Files from the repository that pages read at build time (spec §9: static pages). */
import path from "node:path";
import { REPO_URL } from "./site";

/** The repository root. Next.js and vitest both run from `web/`. */
export const REPO_ROOT = path.resolve(process.cwd(), "..");

/** Link to a repository file (path relative to the root) on the public repository. */
export function repoFileUrl(file: string): string {
  return `${REPO_URL}/blob/main/${file.split(path.sep).join("/")}`;
}
