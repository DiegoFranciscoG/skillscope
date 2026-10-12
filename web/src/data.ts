// Loading and live updates. index.json is polled every 5 minutes with If-None-Match: an
// unchanged build costs a 304 with no body. A new build_id is applied in place (no reload).
import { Embeddings, type EmbeddingsMeta } from "./search/embeddings";
import type { DemandData, Detail, IndexData } from "./types";

export const INDEX_URL = "data/index.json";
export const POLL_MS = 5 * 60 * 1000;

export type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;

export interface UpdateEvent {
  kind: "updated" | "unchanged" | "offline";
  data?: IndexData;
  added?: string[];
}

function isIndex(value: unknown): value is IndexData {
  const data = value as Partial<IndexData> | null;
  return !!data && typeof data.build_id === "string" && Array.isArray(data.items);
}

export class Updater {
  private etag: string | null = null;
  private buildId: string | null = null;
  private timer: ReturnType<typeof setInterval> | null = null;
  lastCheck = 0;
  failing = false;

  constructor(
    private readonly onEvent: (event: UpdateEvent) => void,
    private readonly fetcher: Fetcher = (input, init) => fetch(input, init),
    private readonly now: () => number = Date.now,
  ) {}

  /** First load: throws when nothing can be shown, the caller renders an error state. */
  async load(): Promise<IndexData> {
    const response = await this.fetcher(INDEX_URL, { cache: "no-cache" });
    if (!response.ok) throw new Error(`index.json: HTTP ${response.status}`);
    const data: unknown = await response.json();
    if (!isIndex(data)) throw new Error("index.json: formato inesperado");
    this.etag = response.headers.get("etag");
    this.buildId = data.build_id;
    this.lastCheck = this.now();
    return data;
  }

  async check(): Promise<UpdateEvent> {
    this.lastCheck = this.now();
    let event: UpdateEvent;
    try {
      const headers: Record<string, string> = {};
      if (this.etag) headers["If-None-Match"] = this.etag;
      const response = await this.fetcher(INDEX_URL, { cache: "no-store", headers });
      if (response.status === 304) {
        event = { kind: "unchanged" };
      } else if (!response.ok) {
        event = { kind: "offline" };
      } else {
        const data: unknown = await response.json();
        if (!isIndex(data)) {
          event = { kind: "offline" };
        } else {
          this.etag = response.headers.get("etag");
          if (data.build_id === this.buildId) {
            event = { kind: "unchanged" };
          } else {
            this.buildId = data.build_id;
            event = { kind: "updated", data };
          }
        }
      }
    } catch {
      event = { kind: "offline" };
    }
    this.failing = event.kind === "offline";
    this.onEvent(event);
    return event;
  }

  start(): void {
    if (this.timer) return;
    this.timer = setInterval(() => void this.check(), POLL_MS);
    document.addEventListener("visibilitychange", this.onVisibility);
    window.addEventListener("online", this.onOnline);
  }

  stop(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    document.removeEventListener("visibilitychange", this.onVisibility);
    window.removeEventListener("online", this.onOnline);
  }

  private readonly onVisibility = (): void => {
    if (document.visibilityState === "visible" && this.now() - this.lastCheck >= POLL_MS) {
      void this.check();
    }
  };

  private readonly onOnline = (): void => {
    void this.check();
  };
}

/** Lazy, per-build caches for the files the list does not need at startup. */
export class DataCache {
  private details = new Map<string, Promise<Record<string, Detail>>>();
  private embeddings: Promise<Embeddings | null> | null = null;
  private demand: Promise<DemandData | null> | null = null;

  constructor(
    private files: Record<string, string>,
    private readonly fetcher: Fetcher = (input, init) => fetch(input, init),
  ) {}

  reset(files: Record<string, string>): void {
    this.files = files;
    this.details.clear();
    this.embeddings = null;
    this.demand = null;
  }

  async detail(category: string, id: string): Promise<Detail | null> {
    const url = this.files[`detail:${category}`];
    if (!url) return null;
    let shard = this.details.get(category);
    if (!shard) {
      shard = this.fetcher(url).then(async (r) => {
        if (!r.ok) throw new Error(`detail ${category}: HTTP ${r.status}`);
        return ((await r.json()) as { items: Record<string, Detail> }).items;
      });
      shard.catch(() => this.details.delete(category));
      this.details.set(category, shard);
    }
    return (await shard)[id] ?? null;
  }

  loadEmbeddings(): Promise<Embeddings | null> {
    if (!this.embeddings) {
      const binary = this.files.embeddings;
      const meta = this.files.embeddings_meta;
      this.embeddings =
        binary && meta
          ? Promise.all([this.fetcher(binary), this.fetcher(meta)])
              .then(async ([b, m]) => {
                if (!b.ok || !m.ok) return null;
                return new Embeddings(await b.arrayBuffer(), (await m.json()) as EmbeddingsMeta);
              })
              .catch(() => null)
          : Promise.resolve(null);
    }
    return this.embeddings;
  }

  loadDemand(): Promise<DemandData | null> {
    if (!this.demand) {
      const url = this.files.demand;
      this.demand = url
        ? this.fetcher(url)
            .then(async (r) => (r.ok ? ((await r.json()) as DemandData) : null))
            .catch(() => null)
        : Promise.resolve(null);
    }
    return this.demand;
  }
}
