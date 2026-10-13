// Live GitHub search for when nothing in Skillscope fits. It runs only when the reader presses
// the button: the query then goes to GitHub's public search API, with no account, cookies or
// referrer (the API allows cross-origin requests, docs/investigacion.md #62). Results are
// untrusted text shown through textContent, and only github.com links are accepted.
import type { Fetcher } from "./data";

export const GITHUB_SEARCH = "https://api.github.com/search/repositories";
const REPO_ID = /^[A-Za-z0-9][A-Za-z0-9-]{0,38}\/[A-Za-z0-9._-]{1,100}$/;
const MAX_TERMS = 120;

export interface LiveRepo {
  id: string;
  description: string;
  stars: number;
  url: string;
  pushedAt: string | null;
}

export type LiveResult = { ok: true; repos: LiveRepo[] } | { ok: false; reason: string };

/** The reader's words (letters, digits, a few symbols) plus filters for maintained projects. */
export function liveQuery(query: string): string {
  const terms = query
    .replace(/[^\p{L}\p{N}\s.+#-]/gu, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, MAX_TERMS);
  return `${terms} fork:false archived:false`;
}

function toRepo(item: Record<string, unknown>): LiveRepo | null {
  const id = typeof item.full_name === "string" ? item.full_name : "";
  if (!REPO_ID.test(id)) return null;
  const url = `https://github.com/${id}`;
  if (item.html_url !== url) return null;
  return {
    id,
    description: typeof item.description === "string" ? item.description.slice(0, 300) : "",
    stars: typeof item.stargazers_count === "number" ? item.stargazers_count : 0,
    url,
    pushedAt: typeof item.pushed_at === "string" ? item.pushed_at : null,
  };
}

export async function searchGitHub(query: string, fetcher: Fetcher): Promise<LiveResult> {
  const url = `${GITHUB_SEARCH}?q=${encodeURIComponent(liveQuery(query))}&per_page=10`;
  let response: Response;
  try {
    response = await fetcher(url, {
      credentials: "omit",
      referrerPolicy: "no-referrer",
      headers: { Accept: "application/vnd.github+json" },
    });
  } catch {
    return { ok: false, reason: "No se pudo conectar con GitHub." };
  }
  if (response.status === 403 || response.status === 429) {
    return { ok: false, reason: "GitHub permite 10 búsquedas por minuto sin cuenta; prueba de nuevo en un minuto." };
  }
  if (!response.ok) return { ok: false, reason: `GitHub respondió con el código ${response.status}.` };
  const data = (await response.json()) as { items?: unknown };
  const items = Array.isArray(data.items) ? (data.items as Record<string, unknown>[]) : [];
  return { ok: true, repos: items.map(toRepo).filter((repo): repo is LiveRepo => repo !== null) };
}
