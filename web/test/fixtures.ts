import type { IndexData, Item } from "../src/types";

export function item(overrides: Partial<Item> = {}): Item {
  return {
    id: "acme/tool",
    owner: "acme",
    name: "tool",
    type: "skill",
    category: "development",
    categories: [],
    cause: "automate",
    score: 50,
    components: { quality: 20, maintenance: 10, adoption: 10, social: 0, utility: 10, risk: 0 },
    risk: { level: 0, penalty: 0, flags: [] },
    stars: 10,
    forks: 1,
    pushed_at: "2026-10-01T00:00:00Z",
    license: "MIT",
    summary: "Skill de desarrollo de software.",
    keywords: [],
    install: null,
    counts: {},
    first_seen: "2026-01-01T00:00:00Z",
    mentions_30d: 0,
    trend: 0,
    co: [],
    sample: false,
    ...overrides,
  };
}

export function index(items: Item[], overrides: Partial<IndexData> = {}): IndexData {
  return {
    schema_version: 1,
    build_id: "20261012T120000Z-aaaaaaa",
    built_at: "2026-10-12T12:00:00Z",
    site_url: "https://example.test/skillscope/",
    totals: { repos: items.length, catalog: items.length, artifacts: {}, by_type: {}, by_category: {}, by_risk: {} },
    sources: [],
    labels: { types: { skill: "Skill suelta" }, categories: { development: "Desarrollo" } },
    files: {},
    lists: { most_used: [], most_mentioned: [], trending: [], most_useful: [], safest: [], riskiest: [], most_needed: [] },
    gaps: 0,
    items,
    ...overrides,
  };
}

/** Build an embeddings.bin payload in the same layout as indexer/embeddings.py. */
export function encodeEmbeddings(docs: number[][], termVectors: number[][]): ArrayBuffer {
  const dims = docs[0]?.length ?? termVectors[0]?.length ?? 0;
  const docBytes = docs.length * dims;
  const padding = (4 - ((16 + docBytes) % 4)) % 4;
  const size = 16 + docBytes + padding + termVectors.length * 4 + termVectors.length * dims;
  const buffer = new ArrayBuffer(size);
  const view = new DataView(buffer);
  [..."SKSE"].forEach((c, i) => view.setUint8(i, c.charCodeAt(0)));
  view.setUint16(4, 1, true);
  view.setUint16(6, dims, true);
  view.setUint32(8, docs.length, true);
  view.setUint32(12, termVectors.length, true);
  let offset = 16;
  for (const doc of docs) {
    const norm = Math.hypot(...doc) || 1;
    for (const value of doc) view.setInt8(offset++, Math.round((value / norm) * 127));
  }
  offset += padding;
  const scales = termVectors.map((row) => Math.max(...row.map(Math.abs)) / 127 || 1);
  scales.forEach((scale) => {
    view.setFloat32(offset, scale, true);
    offset += 4;
  });
  termVectors.forEach((row, t) => {
    for (const value of row) view.setInt8(offset++, Math.round(value / scales[t]!));
  });
  return buffer;
}
