// BM25 (Robertson & Zaragoza, 2009) with k1 = 1.2 and b = 0.75 (docs/algoritmo.md §3.3).
// Field weights are applied by repeating tokens: name ×3, keywords ×2, the rest ×1.

export interface BmDocument {
  id: string;
  fields: ReadonlyArray<readonly [string[], number]>; // tokens and weight
}

const K1 = 1.2;
const B = 0.75;

export class Bm25Index {
  private readonly postings = new Map<string, Map<number, number>>();
  private readonly lengths: number[] = [];
  private readonly ids: string[] = [];
  private averageLength = 0;

  constructor(documents: BmDocument[]) {
    documents.forEach((doc, index) => {
      this.ids.push(doc.id);
      let length = 0;
      for (const [tokens, weight] of doc.fields) {
        for (const token of tokens) {
          let docs = this.postings.get(token);
          if (!docs) {
            docs = new Map();
            this.postings.set(token, docs);
          }
          docs.set(index, (docs.get(index) ?? 0) + weight);
          length += weight;
        }
      }
      this.lengths.push(length);
    });
    const total = this.lengths.reduce((sum, value) => sum + value, 0);
    this.averageLength = documents.length ? total / documents.length : 0;
  }

  get size(): number {
    return this.ids.length;
  }

  idOf(index: number): string {
    return this.ids[index] ?? "";
  }

  /** Raw BM25 score per document index (only documents with at least one term). */
  score(queryTokens: string[]): Map<number, number> {
    return new Map([...this.match(queryTokens)].map(([index, m]) => [index, m.score]));
  }

  /** BM25 score plus how many distinct query terms each document contains. */
  match(queryTokens: string[]): Map<number, { score: number; matched: number }> {
    const result = new Map<number, { score: number; matched: number }>();
    const n = this.ids.length;
    for (const term of new Set(queryTokens)) {
      const docs = this.postings.get(term);
      if (!docs) continue;
      const idf = Math.log(1 + (n - docs.size + 0.5) / (docs.size + 0.5));
      for (const [index, tf] of docs) {
        const length = this.lengths[index] ?? 0;
        const norm = tf + K1 * (1 - B + (B * length) / (this.averageLength || 1));
        const entry = result.get(index) ?? { score: 0, matched: 0 };
        entry.score += (idf * tf * (K1 + 1)) / norm;
        entry.matched += 1;
        result.set(index, entry);
      }
    }
    return result;
  }
}
