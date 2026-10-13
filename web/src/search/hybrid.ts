// Search by need: BM25 + LSA similarity + repository score, in three blocks
// (docs/algoritmo.md §3.3).
import type { Item } from "../types";
import { Bm25Index } from "./bm25";
import type { Embeddings } from "./embeddings";
import { tokens } from "./tokenize";

export const MAX_QUERY = 200;
const W_SEM = 0.45;
const W_LEX = 0.35;
const W_SCORE = 0.2;
const BLOCK_SIZE = 8;
const TOGETHER_SIZE = 6;
// "Se le parece" (measured on the live index, 2026-10-13): documents about agents share a
// semantic background of ~0.40-0.45, while genuine matches score 0.5-0.85.
const SIMILAR_SEM_WITH_WORDS = 0.3; // shares query words and some meaning
const SIMILAR_SEM_ALONE = 0.55; // no shared word: only clearly related meaning counts

export interface Hit {
  item: Item;
  final: number;
  lex: number;
  sem: number;
  coverage: number; // share of the query terms the repository contains
}

export interface SearchResult {
  query: string;
  exact: Hit[];
  similar: Hit[];
  together: Item[];
  semantic: boolean;
  elapsedMs: number;
}

/** Trim, drop control characters and cap the length (validated input, docs §3.3). */
export function cleanQuery(raw: string): string {
  return raw.replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim().slice(0, MAX_QUERY);
}

export function documentFields(item: Item, labels: Record<string, string>): BmFields {
  return [
    [tokens(`${item.name.replace(/[-_]/g, " ")} ${item.owner}`), 3],
    [tokens(item.keywords.join(" ")), 2],
    [tokens(item.summary), 1],
    [tokens(`${labels[item.type] ?? item.type} ${labels[item.category] ?? item.category} ${item.type} ${item.category}`), 1],
  ];
}

type BmFields = ReadonlyArray<readonly [string[], number]>;

/** "Se le parece": shares part of the query and some meaning, or clearly related meaning. */
export function similarEnough(hit: Pick<Hit, "lex" | "sem" | "coverage">, semantic: boolean): boolean {
  if (!semantic) return hit.coverage >= 0.5 && hit.lex >= 0.2; // meaning not loaded yet
  return (hit.coverage >= 1 / 3 && hit.sem >= SIMILAR_SEM_WITH_WORDS) || hit.sem >= SIMILAR_SEM_ALONE;
}

export class SearchEngine {
  private readonly index: Bm25Index;
  private readonly position = new Map<string, number>();
  private embeddings: Embeddings | null = null;
  private embeddingRow = new Map<string, number>();

  constructor(
    private readonly items: Item[],
    labels: Record<string, string>,
  ) {
    this.index = new Bm25Index(items.map((item) => ({ id: item.id, fields: documentFields(item, labels) })));
    items.forEach((item, i) => this.position.set(item.id, i));
  }

  attachEmbeddings(embeddings: Embeddings): void {
    this.embeddings = embeddings;
    this.embeddingRow = new Map(embeddings.ids.map((id, i) => [id, i]));
  }

  get hasEmbeddings(): boolean {
    return this.embeddings !== null;
  }

  search(raw: string): SearchResult {
    const started = performance.now();
    const query = cleanQuery(raw);
    const empty: SearchResult = { query, exact: [], similar: [], together: [], semantic: false, elapsedMs: 0 };
    if (!query) return empty;

    const queryTerms = new Set(tokens(query));
    const lexical = this.index.match([...queryTerms]);
    let maxLex = 0;
    for (const value of lexical.values()) maxLex = Math.max(maxLex, value.score);

    const sims = new Map<number, number>();
    const vector = this.embeddings?.project(query) ?? null;
    if (vector && this.embeddings) {
      const all = this.embeddings.similarities(vector);
      all.forEach((sim, row) => {
        if (sim <= 0) return;
        const index = this.position.get(this.embeddings!.ids[row] ?? "");
        if (index !== undefined) sims.set(index, sim);
      });
    }

    const candidates = new Set<number>([...lexical.keys(), ...sims.keys()]);
    const hits: Hit[] = [];
    for (const index of candidates) {
      const item = this.items[index];
      if (!item) continue;
      const match = lexical.get(index);
      const lex = maxLex && match ? match.score / maxLex : 0;
      const coverage = queryTerms.size && match ? match.matched / queryTerms.size : 0;
      const sem = Math.max(0, sims.get(index) ?? 0);
      hits.push({ item, lex, sem, coverage, final: W_SEM * sem + W_LEX * lex + (W_SCORE * item.score) / 100 });
    }
    hits.sort((a, b) => b.final - a.final || b.item.score - a.item.score || a.item.id.localeCompare(b.item.id));

    const semantic = vector !== null;
    // BM25 is normalised by the best match, so a weak query would still produce a "1.0";
    // coverage keeps results honest: the repository must contain enough of the query.
    const exact = hits
      .filter((h) => h.lex >= 0.5 && h.coverage >= 0.5 && (!semantic || h.sem >= 0.25))
      .slice(0, BLOCK_SIZE);
    const shown = new Set(exact.map((h) => h.item.id));
    const similar = hits
      .filter((h) => !shown.has(h.item.id) && similarEnough(h, semantic))
      .slice(0, BLOCK_SIZE);
    similar.forEach((h) => shown.add(h.item.id));

    const together: Item[] = [];
    for (const hit of [...exact, ...similar].slice(0, 3)) {
      for (const id of hit.item.co) {
        const index = this.position.get(id);
        const item = index === undefined ? undefined : this.items[index];
        if (item && !shown.has(id)) {
          shown.add(id);
          together.push(item);
        }
      }
    }
    together.sort((a, b) => b.score - a.score);

    return {
      query,
      exact,
      similar,
      together: together.slice(0, TOGETHER_SIZE),
      semantic,
      elapsedMs: performance.now() - started,
    };
  }
}
