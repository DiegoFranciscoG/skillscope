// Live GitHub search for when nothing in Skillscope fits. It runs only when the reader presses
// the button: the query then goes to GitHub's public search API, with no account, cookies or
// referrer (the API allows cross-origin requests, docs/investigacion.md #62). Results are
// untrusted text shown through textContent, and only github.com links are accepted.
//
// Without an account GitHub allows 10 searches a minute per visitor. Answers are cached for the
// session and the rate-limit headers GitHub exposes are read, so a repeated search costs nothing
// and an exhausted quota shows a countdown instead of an error.
import type { Fetcher } from "./data";

export const GITHUB_SEARCH = "https://api.github.com/search/repositories";
const REPO_ID = /^[A-Za-z0-9][A-Za-z0-9-]{0,38}\/[A-Za-z0-9._-]{1,100}$/;
const MAX_TERMS = 120;
const CACHE_PREFIX = "skillscope:github:";
const CACHE_MS = 10 * 60 * 1000;
const BLOCK_KEY = `${CACHE_PREFIX}blocked-until`;

export interface LiveRepo {
  id: string;
  description: string;
  stars: number;
  url: string;
  pushedAt: string | null;
}

export type LiveResult =
  | { ok: true; repos: LiveRepo[]; cached?: boolean }
  | { ok: false; reason: string; retryInSeconds?: number };

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

/** sessionStorage can be missing or throw (private mode, blocked storage): never required. */
function sessionStore(): Storage | null {
  try {
    return typeof sessionStorage === "undefined" ? null : sessionStorage;
  } catch {
    return null;
  }
}

function waitMessage(seconds: number): string {
  return `GitHub permite 10 búsquedas por minuto sin cuenta; podrás buscar de nuevo en ${seconds} s. Mientras tanto revisa los repositorios en cola de arriba.`;
}

export class LiveSearch {
  constructor(
    private readonly fetcher: Fetcher,
    private readonly storage: Storage | null = sessionStore(),
    private readonly now: () => number = Date.now,
  ) {}

  /** Seconds until GitHub accepts another anonymous search from this visitor (0 = now). */
  waitSeconds(): number {
    const until = Number(this.read(BLOCK_KEY) ?? 0);
    return Math.max(0, Math.ceil((until - this.now()) / 1000));
  }

  async search(query: string): Promise<LiveResult> {
    const key = `${CACHE_PREFIX}${liveQuery(query).toLowerCase()}`;
    const cached = this.cachedRepos(key);
    if (cached) return { ok: true, repos: cached, cached: true };
    const wait = this.waitSeconds();
    if (wait > 0) return { ok: false, reason: waitMessage(wait), retryInSeconds: wait };

    const url = `${GITHUB_SEARCH}?q=${encodeURIComponent(liveQuery(query))}&per_page=10`;
    let response: Response;
    try {
      response = await this.fetcher(url, {
        credentials: "omit",
        referrerPolicy: "no-referrer",
        headers: { Accept: "application/vnd.github+json" },
      });
    } catch {
      return { ok: false, reason: "No se pudo conectar con GitHub." };
    }
    const remaining = Number(response.headers.get("x-ratelimit-remaining"));
    const resetAt = Number(response.headers.get("x-ratelimit-reset")) * 1000;
    const exhausted = response.status === 403 || response.status === 429 || remaining === 0;
    if (exhausted && resetAt > this.now()) this.write(BLOCK_KEY, String(resetAt));
    if (response.status === 403 || response.status === 429) {
      const wait = this.waitSeconds() || 60;
      return { ok: false, reason: waitMessage(wait), retryInSeconds: wait };
    }
    if (!response.ok) return { ok: false, reason: `GitHub respondió con el código ${response.status}.` };
    const data = (await response.json()) as { items?: unknown };
    const items = Array.isArray(data.items) ? (data.items as Record<string, unknown>[]) : [];
    const repos = items.map(toRepo).filter((repo): repo is LiveRepo => repo !== null);
    this.write(key, JSON.stringify({ at: this.now(), repos }));
    return { ok: true, repos };
  }

  private cachedRepos(key: string): LiveRepo[] | null {
    try {
      const raw = this.read(key);
      if (!raw) return null;
      const entry = JSON.parse(raw) as { at: number; repos: LiveRepo[] };
      if (this.now() - entry.at > CACHE_MS || !Array.isArray(entry.repos)) return null;
      return entry.repos.filter((repo) => REPO_ID.test(repo.id) && repo.url === `https://github.com/${repo.id}`);
    } catch {
      return null;
    }
  }

  private read(key: string): string | null {
    try {
      return this.storage?.getItem(key) ?? null;
    } catch {
      return null;
    }
  }

  private write(key: string, value: string): void {
    try {
      this.storage?.setItem(key, value);
    } catch {
      // Storage full or blocked: the cache is a convenience only.
    }
  }
}
