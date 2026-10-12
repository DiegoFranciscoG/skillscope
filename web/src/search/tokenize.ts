// Same algorithm as analyzer/text.py (docs/algoritmo.md §3.1). The shared cases in
// data/samples/tokenize-cases.json are checked by pytest and by Vitest.
import { LEXICON, PHRASES, PROTECTED, STOPWORDS } from "./lexicon.generated";

const PHRASE_PATTERNS = PHRASES.map(([pattern, replacement]) => [new RegExp(pattern, "g"), replacement] as const);
const WORD = /[a-z0-9]+/g;
const COMBINING = /\p{M}/gu;
const DIGITS = /^\d+$/;

export function fold(text: string): string {
  return text.normalize("NFKD").replace(COMBINING, "").toLowerCase();
}

export function normalize(text: string): string {
  let folded = fold(text);
  for (const [pattern, replacement] of PHRASE_PATTERNS) folded = folded.replace(pattern, replacement);
  return folded;
}

export function words(text: string): string[] {
  const out: string[] = [];
  for (const raw of normalize(text).match(WORD) ?? []) {
    if (raw.length < 2 || DIGITS.test(raw) || STOPWORDS.has(raw)) continue;
    out.push(LEXICON[raw] ?? raw);
  }
  return out;
}

const stemCache = new Map<string, string>();

export function stem(word: string): string {
  const cached = stemCache.get(word);
  if (cached !== undefined) return cached;
  let w = word;
  if (!(PROTECTED.has(word) || word.length <= 3)) {
    if (w.endsWith("ies") && w.length > 4) {
      w = w.slice(0, -3) + "y";
    } else if (w.endsWith("sses")) {
      w = w.slice(0, -2);
    } else if (w.endsWith("s") && !w.endsWith("ss") && !w.endsWith("us") && !w.endsWith("is") && w.length > 3) {
      w = w.slice(0, -1);
    }
    if (w.endsWith("ing") && w.length > 5) {
      w = w.slice(0, -3);
      if (w.length > 3 && w.at(-1) === w.at(-2) && !"lsz".includes(w.at(-1) ?? "")) w = w.slice(0, -1);
    } else if (w.endsWith("ed") && w.length > 4) {
      w = w.slice(0, -2);
      if (w.length > 3 && w.at(-1) === w.at(-2) && !"lsz".includes(w.at(-1) ?? "")) w = w.slice(0, -1);
    }
    if (w.endsWith("e") && w.length > 3) w = w.slice(0, -1);
  }
  stemCache.set(word, w);
  return w;
}

export function tokens(text: string): string[] {
  return words(text).map(stem);
}
