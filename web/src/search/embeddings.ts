// Reader for data/embeddings.bin + data/embeddings.json (format in indexer/embeddings.py).
import { tokens } from "./tokenize";

export interface EmbeddingsMeta {
  schema_version: number;
  dims: number;
  ids: string[];
  terms: string[];
  idf: number[];
}

export class Embeddings {
  readonly dims: number;
  readonly ids: string[];
  private readonly docs: Int8Array;
  private readonly termScales: Float32Array;
  private readonly termVectors: Int8Array;
  private readonly termIndex: Map<string, number>;
  private readonly idf: number[];

  constructor(buffer: ArrayBuffer, meta: EmbeddingsMeta) {
    const view = new DataView(buffer);
    const magic = String.fromCharCode(view.getUint8(0), view.getUint8(1), view.getUint8(2), view.getUint8(3));
    if (magic !== "SKSE") throw new Error("embeddings: formato desconocido");
    const dims = view.getUint16(6, true);
    const nDocs = view.getUint32(8, true);
    const nTerms = view.getUint32(12, true);
    if (dims !== meta.dims || nDocs !== meta.ids.length || nTerms !== meta.terms.length) {
      throw new Error("embeddings: el binario no coincide con el índice");
    }
    let offset = 16;
    this.docs = new Int8Array(buffer, offset, nDocs * dims);
    offset += nDocs * dims;
    offset += (4 - (offset % 4)) % 4;
    this.termScales = new Float32Array(buffer, offset, nTerms);
    offset += nTerms * 4;
    this.termVectors = new Int8Array(buffer, offset, nTerms * dims);
    this.dims = dims;
    this.ids = meta.ids;
    this.idf = meta.idf;
    this.termIndex = new Map(meta.terms.map((term, i) => [term, i]));
  }

  /** Unit vector of the query in the latent space, or null when no term is known. */
  project(text: string): Float32Array | null {
    if (!this.dims) return null;
    const counts = new Map<number, number>();
    for (const token of tokens(text)) {
      const index = this.termIndex.get(token);
      if (index !== undefined) counts.set(index, (counts.get(index) ?? 0) + 1);
    }
    if (!counts.size) return null;
    const weights: [number, number][] = [];
    let norm = 0;
    for (const [index, count] of counts) {
      const weight = (1 + Math.log(count)) * (this.idf[index] ?? 1);
      weights.push([index, weight]);
      norm += weight * weight;
    }
    norm = Math.sqrt(norm);
    const vector = new Float32Array(this.dims);
    for (const [index, weight] of weights) {
      const scale = (this.termScales[index] ?? 0) * (weight / norm);
      const base = index * this.dims;
      for (let d = 0; d < this.dims; d++) vector[d]! += (this.termVectors[base + d] ?? 0) * scale;
    }
    let length = 0;
    for (let d = 0; d < this.dims; d++) length += vector[d]! * vector[d]!;
    length = Math.sqrt(length);
    if (!length) return null;
    for (let d = 0; d < this.dims; d++) vector[d]! /= length;
    return vector;
  }

  /** Cosine similarity of every document with a unit query vector. */
  similarities(query: Float32Array): Float32Array {
    const out = new Float32Array(this.ids.length);
    for (let i = 0; i < this.ids.length; i++) {
      let dot = 0;
      const base = i * this.dims;
      for (let d = 0; d < this.dims; d++) dot += (this.docs[base + d] ?? 0) * query[d]!;
      out[i] = dot / 127;
    }
    return out;
  }
}
