import { describe, expect, it, vi } from "vitest";
import { DataCache, type Fetcher, INDEX_URL, Updater } from "../src/data";
import { index, item } from "./fixtures";

function response(status: number, body?: unknown, etag?: string): Response {
  return new Response(status === 304 ? null : JSON.stringify(body), {
    status,
    headers: etag ? { etag } : {},
  });
}

describe("Updater", () => {
  it("loads, then answers 304 cheaply and applies a new build", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    const queue = [
      response(200, index([item()]), '"v1"'),
      response(304),
      response(200, index([item(), item({ id: "acme/new" })], { build_id: "b2" }), '"v2"'),
    ];
    const fetcher: Fetcher = async (url, init) => {
      calls.push({ url, init });
      return queue.shift()!;
    };
    const events: string[] = [];
    const updater = new Updater((e) => events.push(e.kind), fetcher, () => 1000);
    const data = await updater.load();
    expect(data.items).toHaveLength(1);
    expect((await updater.check()).kind).toBe("unchanged");
    expect((calls[1]!.init!.headers as Record<string, string>)["If-None-Match"]).toBe('"v1"');
    expect(calls[1]!.init!.cache).toBe("no-store");
    const update = await updater.check();
    expect(update.kind).toBe("updated");
    expect(update.data!.items).toHaveLength(2);
    expect(events).toEqual(["unchanged", "updated"]);
    expect(calls.every((c) => c.url === INDEX_URL)).toBe(true);
  });

  it("keeps the old data when the network fails", async () => {
    const fetcher: Fetcher = vi.fn().mockResolvedValueOnce(response(200, index([item()]))).mockRejectedValueOnce(new Error("offline"));
    const updater = new Updater(() => undefined, fetcher);
    await updater.load();
    expect((await updater.check()).kind).toBe("offline");
    expect(updater.failing).toBe(true);
  });

  it("ignores a response with the same build id and rejects malformed data", async () => {
    const same = index([item()]);
    const fetcher: Fetcher = vi
      .fn()
      .mockResolvedValueOnce(response(200, same))
      .mockResolvedValueOnce(response(200, same))
      .mockResolvedValueOnce(response(200, { nope: true }))
      .mockResolvedValueOnce(response(500, {}));
    const updater = new Updater(() => undefined, fetcher);
    await updater.load();
    expect((await updater.check()).kind).toBe("unchanged");
    expect((await updater.check()).kind).toBe("offline");
    expect((await updater.check()).kind).toBe("offline");
    const broken = new Updater(() => undefined, vi.fn().mockResolvedValue(response(200, { build_id: 1 })));
    await expect(broken.load()).rejects.toThrow("formato inesperado");
  });
});

describe("DataCache", () => {
  it("fetches each shard once per build and resets on a new build", async () => {
    const fetcher = vi.fn(async (url: string) =>
      url.includes("detail") ? response(200, { items: { "acme/tool": { id: "acme/tool" } } }) : response(200, { items: [], topics: [], gaps: [] }),
    );
    const cache = new DataCache({ "detail:development": "data/detail/development.json?v=1", demand: "data/demand.json?v=1" }, fetcher);
    expect((await cache.detail("development", "acme/tool"))?.id).toBe("acme/tool");
    await cache.detail("development", "acme/tool");
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(await cache.detail("unknown", "x")).toBeNull();
    expect(await cache.loadDemand()).not.toBeNull();
    cache.reset({ "detail:development": "data/detail/development.json?v=2" });
    await cache.detail("development", "acme/tool");
    expect(fetcher).toHaveBeenLastCalledWith("data/detail/development.json?v=2");
    expect(await cache.loadEmbeddings()).toBeNull();
    expect(await cache.loadDemand()).toBeNull();
  });
});
