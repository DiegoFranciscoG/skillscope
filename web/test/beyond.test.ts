import { describe, expect, it, vi } from "vitest";
import { LiveSearch, liveQuery } from "../src/github-live";
import { CandidateIndex } from "../src/search/candidates";
import type { Candidate } from "../src/types";
import { renderBeyond, requestUrl } from "../src/ui/beyond";

const candidate = (id: string, d: string, s = 10, t: string[] = []): Candidate => ({ id, d, t, l: "", s, p: null });

const QUEUE = [
  candidate("makenotion/notion-mcp-server", "Official Notion MCP Server", 4666, ["mcp", "notion"]),
  candidate("acme/spreadsheet-tools", "Excel macros helpers", 50),
  candidate("acme/notion-backup", "Back up a Notion workspace", 30),
];

describe("candidate queue search", () => {
  it("finds queued repositories by name, topics and description", () => {
    const hits = new CandidateIndex(QUEUE).search("notion mcp");
    expect(hits[0]?.candidate.id).toBe("makenotion/notion-mcp-server");
    expect(hits.map((h) => h.candidate.id)).not.toContain("acme/spreadsheet-tools");
  });

  it("needs half of the query terms", () => {
    expect(new CandidateIndex(QUEUE).search("notion kubernetes terraform")).toEqual([]);
  });
});

describe("live GitHub search", () => {
  it("keeps only the reader's words plus maintenance filters", () => {
    expect(liveQuery("notion <script> mcp!!")).toBe("notion script mcp fork:false archived:false");
  });

  it("sends no credentials or referrer and drops anything that is not a github.com repo", async () => {
    const fetcher = vi.fn(async (_input: string, _init?: RequestInit) =>
      new Response(
        JSON.stringify({
          items: [
            { full_name: "makenotion/notion-mcp-server", html_url: "https://github.com/makenotion/notion-mcp-server", description: "Official", stargazers_count: 4666, pushed_at: "2026-10-01T00:00:00Z" },
            { full_name: "evil/x", html_url: "javascript:alert(1)" },
            { full_name: "../../etc", html_url: "https://github.com/../../etc" },
          ],
        }),
        { status: 200 },
      ),
    );
    const result = await new LiveSearch(fetcher, null).search("notion mcp");
    const init = fetcher.mock.calls[0]![1]!;
    expect(init.credentials).toBe("omit");
    expect(init.referrerPolicy).toBe("no-referrer");
    expect(result).toEqual({
      ok: true,
      repos: [{ id: "makenotion/notion-mcp-server", description: "Official", stars: 4666, url: "https://github.com/makenotion/notion-mcp-server", pushedAt: "2026-10-01T00:00:00Z" }],
    });
  });

  it("explains the unauthenticated rate limit", async () => {
    const result = await new LiveSearch(async () => new Response("{}", { status: 403 }), null).search("x");
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toContain("10 búsquedas por minuto");
  });

  it("caches answers for the session and counts down when the quota is spent", async () => {
    const memory = new Map<string, string>();
    const storage = {
      getItem: (key: string) => memory.get(key) ?? null,
      setItem: (key: string, value: string) => void memory.set(key, value),
    } as unknown as Storage;
    let now = Date.parse("2026-10-13T12:00:00Z");
    const resetAt = Math.floor(now / 1000) + 45;
    const fetcher = vi.fn(async () =>
      new Response(
        JSON.stringify({ items: [{ full_name: "a/b", html_url: "https://github.com/a/b" }] }),
        { status: 200, headers: { "x-ratelimit-remaining": "0", "x-ratelimit-reset": String(resetAt) } },
      ),
    );
    const live = new LiveSearch(fetcher, storage, () => now);
    expect((await live.search("notion")).ok).toBe(true);
    const again = await live.search("Notion");
    expect(again.ok && again.cached).toBe(true); // same words: no second request
    expect(fetcher).toHaveBeenCalledTimes(1);
    const other = await live.search("figma");
    expect(other.ok).toBe(false);
    if (!other.ok) expect(other.retryInSeconds).toBe(45);
    expect(fetcher).toHaveBeenCalledTimes(1); // quota spent: GitHub is not asked again
    now += 46_000;
    expect(live.waitSeconds()).toBe(0);
  });
});

describe("beyond the index", () => {
  it("prefills the analysis request form", () => {
    const url = new URL(requestUrl("acme/notion-backup"));
    expect(url.hostname).toBe("github.com");
    expect(url.searchParams.get("template")).toBe("skill-request.yml");
    expect(url.searchParams.get("repository")).toBe("acme/notion-backup");
  });

  it("shows queued matches as text and runs the live search only on click", async () => {
    const container = document.createElement("div");
    const searchLive = vi.fn(async () => ({ ok: true as const, repos: [{ id: "x/<b>bold</b>", description: "<img src=x onerror=alert(1)>", stars: 1, url: "https://github.com/x/y", pushedAt: null }] }));
    renderBeyond(container, "notion", {
      loadCandidates: async () => QUEUE,
      searchGitHub: searchLive,
      inIndex: (id) => id === "acme/notion-backup",
      onOpen: vi.fn(),
      now: Date.parse("2026-10-13T00:00:00Z"),
    });
    await Promise.resolve();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(container.textContent).toContain("makenotion/notion-mcp-server");
    expect(container.textContent).toContain("ya analizado");
    expect(searchLive).not.toHaveBeenCalled();
    container.querySelector<HTMLButtonElement>("button")!.click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(searchLive).toHaveBeenCalledWith("notion");
    expect(container.querySelector("img")).toBeNull(); // third-party text never becomes markup
    expect(container.textContent).toContain("<img src=x onerror=alert(1)>");
  });
});
