// Application state with a tiny observer, mirrored in the URL so every view can be shared.
import type { IndexData, Item } from "./types";

export const TABS = [
  ["explore", "Explorar"],
  ["most_used", "Más usadas"],
  ["most_mentioned", "Más mencionadas"],
  ["trending", "En tendencia"],
  ["most_useful", "Más útiles"],
  ["safest", "Más seguras"],
  ["riskiest", "Más riesgosas"],
  ["gaps", "Huecos"],
] as const;

export type Tab = (typeof TABS)[number][0];
export type Sort = "score" | "stars" | "recent" | "new";

export interface Filters {
  type: string;
  category: string;
  risk: string;
  sort: Sort;
}

export interface State {
  data: IndexData | null;
  byId: Map<string, Item>;
  tab: Tab;
  query: string;
  filters: Filters;
  selected: string | null;
  sessionNew: Map<string, number>;
  offline: boolean;
}

type Listener = (state: State, changed: ReadonlySet<keyof State>) => void;

const TAB_IDS = new Set<string>(TABS.map(([id]) => id));
const SORTS = new Set<string>(["score", "stars", "recent", "new"]);

export function initialState(search: string): State {
  const params = new URLSearchParams(search);
  const tab = params.get("tab") ?? "explore";
  const sort = params.get("sort") ?? "score";
  return {
    data: null,
    byId: new Map(),
    tab: (TAB_IDS.has(tab) ? tab : "explore") as Tab,
    query: (params.get("q") ?? "").slice(0, 200),
    filters: {
      type: params.get("type") ?? "",
      category: params.get("cat") ?? "",
      risk: params.get("risk") ?? "",
      sort: (SORTS.has(sort) ? sort : "score") as Sort,
    },
    selected: params.get("r"),
    sessionNew: new Map(),
    offline: false,
  };
}

export function toSearch(state: State): string {
  const params = new URLSearchParams();
  if (state.query) params.set("q", state.query);
  if (state.tab !== "explore") params.set("tab", state.tab);
  if (state.filters.type) params.set("type", state.filters.type);
  if (state.filters.category) params.set("cat", state.filters.category);
  if (state.filters.risk) params.set("risk", state.filters.risk);
  if (state.filters.sort !== "score") params.set("sort", state.filters.sort);
  if (state.selected) params.set("r", state.selected);
  const text = params.toString();
  return text ? `?${text}` : "";
}

export class Store {
  private listeners: Listener[] = [];

  constructor(public state: State) {}

  subscribe(listener: Listener): void {
    this.listeners.push(listener);
  }

  set(patch: Partial<State>): void {
    const changed = new Set<keyof State>();
    for (const key of Object.keys(patch) as (keyof State)[]) {
      if (this.state[key] !== patch[key]) changed.add(key);
    }
    if (!changed.size) return;
    this.state = { ...this.state, ...patch };
    for (const listener of this.listeners) listener(this.state, changed);
  }

  /** Apply a new build in place; ids that were not there before are remembered as new. */
  replaceData(data: IndexData, now: number = Date.now()): string[] {
    const previous = this.state.byId;
    const added: string[] = [];
    const sessionNew = new Map(this.state.sessionNew);
    if (previous.size) {
      for (const item of data.items) {
        if (!previous.has(item.id)) {
          added.push(item.id);
          sessionNew.set(item.id, now);
        }
      }
    }
    const byId = new Map(data.items.map((item) => [item.id, item]));
    const selected = this.state.selected && byId.has(this.state.selected) ? this.state.selected : null;
    this.set({ data, byId, sessionNew, selected, offline: false });
    return added;
  }
}

const RISK_ORDER = (item: Item): number => item.risk.penalty;

export function visibleItems(state: State): Item[] {
  const data = state.data;
  if (!data) return [];
  if (state.tab !== "explore" && state.tab !== "gaps") {
    const ids = data.lists[state.tab] as string[];
    return ids.map((id) => state.byId.get(id)).filter((item): item is Item => item !== undefined);
  }
  const { type, category, risk, sort } = state.filters;
  const items = data.items.filter(
    (item) =>
      (!type || item.type === type) &&
      (!category || item.category === category || item.categories.includes(category)) &&
      (!risk || String(item.risk.level) === risk),
  );
  const sorters: Record<Sort, (a: Item, b: Item) => number> = {
    score: (a, b) => b.score - a.score || b.stars - a.stars,
    stars: (a, b) => b.stars - a.stars || b.score - a.score,
    recent: (a, b) => (b.pushed_at ?? "").localeCompare(a.pushed_at ?? "") || b.score - a.score,
    new: (a, b) => b.first_seen.localeCompare(a.first_seen) || b.score - a.score,
  };
  return [...items].sort((a, b) => sorters[sort](a, b) || RISK_ORDER(a) - RISK_ORDER(b) || a.id.localeCompare(b.id));
}
