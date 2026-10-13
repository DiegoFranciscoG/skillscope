// Search over repositories that discovery found but the pipeline has not analyzed yet
// (data/candidates.json, thousands of them). Same BM25 as the index, same coverage rule.
import type { Candidate } from "../types";
import { Bm25Index } from "./bm25";
import { tokens } from "./tokenize";

export interface CandidateHit {
  candidate: Candidate;
  score: number;
}

const MIN_COVERAGE = 0.5; // half of the query terms, as for "Resuelve exactamente eso"

export class CandidateIndex {
  private readonly index: Bm25Index;

  constructor(private readonly items: Candidate[]) {
    this.index = new Bm25Index(
      items.map((item) => ({
        id: item.id,
        fields: [
          [tokens(item.id.replace(/[/_.-]+/g, " ")), 3],
          [tokens(item.t.join(" ").replace(/-/g, " ")), 2],
          [tokens(item.d), 1],
        ],
      })),
    );
  }

  get size(): number {
    return this.items.length;
  }

  /** Best matches: relevance first, popularity as a small tie-breaker. */
  search(query: string, limit = 8): CandidateHit[] {
    const terms = tokens(query);
    const distinct = new Set(terms).size;
    if (!distinct) return [];
    const matches = [...this.index.match(terms)].filter(([, m]) => m.matched / distinct >= MIN_COVERAGE);
    const best = Math.max(0, ...matches.map(([, m]) => m.score)) || 1;
    return matches
      .map(([index, m]) => {
        const candidate = this.items[index]!;
        const popularity = Math.min(1, Math.log10(1 + candidate.s) / 5);
        return { candidate, score: 0.8 * (m.score / best) + 0.2 * popularity };
      })
      .sort((a, b) => b.score - a.score || b.candidate.s - a.candidate.s || a.candidate.id.localeCompare(b.candidate.id))
      .slice(0, limit);
  }
}
