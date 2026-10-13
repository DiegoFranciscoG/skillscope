import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { Bm25Index } from "../src/search/bm25";
import { Embeddings } from "../src/search/embeddings";
import { cleanQuery, MAX_QUERY, SearchEngine, similarEnough } from "../src/search/hybrid";
import { stem, tokens } from "../src/search/tokenize";
import { encodeEmbeddings, item } from "./fixtures";

// Vitest runs from web/, so the shared cases live one level up.
const cases = JSON.parse(readFileSync(resolve(process.cwd(), "../data/samples/tokenize-cases.json"), "utf-8")) as {
  input: string;
  tokens: string[];
}[];

describe("tokenizer parity with Python", () => {
  it.each(cases)("tokenizes %o like analyzer/text.py", ({ input, tokens: expected }) => {
    expect(tokens(input)).toEqual(expected);
  });

  it("stems like the Python version", () => {
    expect(["tests", "running", "libraries", "classes", "code", "pr"].map(stem)).toEqual([
      "test",
      "run",
      "library",
      "class",
      "cod",
      "pr",
    ]);
  });
});

describe("BM25", () => {
  it("ranks documents with more relevant term weight first", () => {
    const index = new Bm25Index([
      { id: "a", fields: [[["review", "pr"], 3]] },
      { id: "b", fields: [[["review"], 1]] },
      { id: "c", fields: [[["calendar"], 1]] },
    ]);
    const scores = index.score(["review", "pr"]);
    expect(scores.get(0)! > scores.get(1)!).toBe(true);
    expect(scores.has(2)).toBe(false);
    expect(index.idOf(0)).toBe("a");
    expect(index.size).toBe(3);
  });
});

describe("embeddings reader", () => {
  const buffer = encodeEmbeddings(
    [
      [1, 0],
      [0, 1],
    ],
    [
      [1, 0],
      [0, 1],
    ],
  );
  const meta = { schema_version: 1, dims: 2, ids: ["a/review", "b/tests"], terms: ["review", "test"], idf: [1, 1] };

  it("projects a query and scores documents by cosine", () => {
    const embeddings = new Embeddings(buffer, meta);
    const vector = embeddings.project("revisar")!;
    const sims = embeddings.similarities(vector);
    expect(sims[0]).toBeGreaterThan(0.9);
    expect(sims[1]).toBeLessThan(0.1);
    expect(embeddings.project("cobol")).toBeNull();
  });

  it("rejects files that do not match the index", () => {
    expect(() => new Embeddings(buffer, { ...meta, ids: ["only/one"] })).toThrow();
    expect(() => new Embeddings(new ArrayBuffer(32), meta)).toThrow();
  });
});

describe("search by need", () => {
  const items = [
    item({ id: "acme/pr-review", name: "pr-review", keywords: ["review", "pr", "diff"], score: 80, co: ["acme/lint"] }),
    item({ id: "acme/lint", name: "lint", keywords: ["lint", "style"], score: 60 }),
    item({ id: "acme/notes", name: "notes", keywords: ["calendar", "meeting"], score: 90 }),
    item({ id: "acme/review-docs", name: "docs", keywords: ["docs", "review"], score: 40 }),
  ];
  const engine = new SearchEngine(items, { skill: "Skill suelta", development: "Desarrollo" });

  it("returns exact, similar and together blocks", () => {
    const result = engine.search("necesito revisar pull requests");
    expect(result.exact.map((h) => h.item.id)).toEqual(["acme/pr-review"]);
    expect(result.similar.map((h) => h.item.id)).toEqual(["acme/review-docs"]);
    expect(result.together.map((i) => i.id)).toEqual(["acme/lint"]);
    expect(result.semantic).toBe(false);
  });

  it("says when nothing matches", () => {
    const result = engine.search("migrar cobol");
    expect(result.exact).toEqual([]);
    expect(result.similar).toEqual([]);
  });

  it("validates and limits the query", () => {
    expect(cleanQuery(`  hola\u0000\u0007mundo  `)).toBe("hola mundo");
    expect(cleanQuery("x".repeat(500))).toHaveLength(MAX_QUERY);
    expect(engine.search("   ").exact).toEqual([]);
  });

  it("answers in under 100 ms with 3,000 repositories (acceptance)", () => {
    const vocab = ["review", "test", "docs", "security", "data", "deploy", "design", "email", "research", "lint"];
    const many = Array.from({ length: 3000 }, (_, i) =>
      item({
        id: `owner${i}/repo${i}`,
        name: `repo-${vocab[i % vocab.length]}-${i}`,
        keywords: [vocab[i % 10]!, vocab[(i * 3) % 10]!, vocab[(i * 7) % 10]!],
        summary: `Skill de ${vocab[i % 10]} y ${vocab[(i + 1) % 10]} con pasos claros.`,
        score: i % 100,
      }),
    );
    const dims = 64;
    const rnd = (seed: number) => () => ((seed = (seed * 1103515245 + 12345) % 2 ** 31) / 2 ** 31) * 2 - 1;
    const random = rnd(42);
    const docs = many.map(() => Array.from({ length: dims }, random));
    const terms = vocab.map(() => Array.from({ length: dims }, random));
    const big = new SearchEngine(many, {});
    big.attachEmbeddings(
      new Embeddings(encodeEmbeddings(docs, terms), {
        schema_version: 1,
        dims,
        ids: many.map((m) => m.id),
        terms: vocab.map((v) => stem(v)),
        idf: vocab.map(() => 1),
      }),
    );
    big.search("warm up");
    const started = performance.now();
    const result = big.search("necesito revisar la seguridad y las pruebas");
    const elapsed = performance.now() - started;
    expect(result.semantic).toBe(true);
    expect(result.exact.length + result.similar.length).toBeGreaterThan(0);
    expect(elapsed).toBeLessThan(100);
  });
});

describe("similar results (thresholds measured on the live index)", () => {
  it("drops background semantic noise and keeps real partial matches", () => {
    // facturación electrónica Ecuador: unrelated skills at sem 0.42-0.45 without a shared word
    expect(similarEnough({ lex: 0, sem: 0.45, coverage: 0 }, true)).toBe(false);
    // base de datos postgres: a Postgres guide with no shared word but clear meaning
    expect(similarEnough({ lex: 0, sem: 0.65, coverage: 0 }, true)).toBe(true);
    // one shared word and some meaning: a partial answer
    expect(similarEnough({ lex: 0.5, sem: 0.38, coverage: 1 / 3 }, true)).toBe(true);
    // one shared word but no meaning in common
    expect(similarEnough({ lex: 1, sem: 0.14, coverage: 1 / 3 }, true)).toBe(false);
    // before embeddings load, half of the words are needed
    expect(similarEnough({ lex: 0.9, sem: 0, coverage: 1 / 3 }, false)).toBe(false);
    expect(similarEnough({ lex: 0.9, sem: 0, coverage: 0.5 }, false)).toBe(true);
  });
});
