import "./styles.css";
import { DataCache, type UpdateEvent, Updater } from "./data";
import { clear, h } from "./dom";
import { ago, clockTime, SOURCE_LABELS } from "./format";
import { SearchEngine } from "./search/hybrid";
import { initialState, Store, TABS, type State, type Tab, toSearch, visibleItems } from "./store";
import type { IndexData, Item } from "./types";
import { renderDrawer } from "./ui/drawer";
import { PAGE, renderList, rowButtons, type RowContext } from "./ui/list";
import { renderError, renderGaps, renderSearch } from "./ui/views";

const $ = <T extends HTMLElement>(id: string): T => {
  const el = document.getElementById(id);
  if (!el) throw new Error(`missing #${id}`);
  return el as T;
};

const ui = {
  status: $<HTMLParagraphElement>("status"),
  search: $<HTMLInputElement>("q"),
  searchForm: $<HTMLFormElement>("search-form"),
  tabs: $<HTMLElement>("tabs"),
  toolbar: $<HTMLDivElement>("toolbar"),
  filters: $<HTMLFormElement>("filters"),
  type: $<HTMLSelectElement>("f-type"),
  category: $<HTMLSelectElement>("f-category"),
  risk: $<HTMLSelectElement>("f-risk"),
  sort: $<HTMLSelectElement>("f-sort"),
  count: $<HTMLParagraphElement>("count"),
  view: $<HTMLElement>("view"),
  layout: document.querySelector<HTMLDivElement>(".layout")!,
  drawer: $<HTMLElement>("drawer"),
  live: $<HTMLParagraphElement>("live"),
  sources: $<HTMLUListElement>("sources-list"),
  sheet: $<HTMLDialogElement>("filters-sheet"),
  sheetBody: $<HTMLDivElement>("sheet-body"),
  filtersOpen: $<HTMLButtonElement>("filters-open"),
  filtersClose: $<HTMLButtonElement>("filters-close"),
};

const store = new Store(initialState(location.search));
const cache = new DataCache({});
let engine: SearchEngine | null = null;
let listLimit = PAGE;
let searchTimer = 0;
let lastFocusedRow: string | null = null;

function announce(text: string): void {
  ui.live.textContent = "";
  window.setTimeout(() => (ui.live.textContent = text), 50);
}

// ---- status --------------------------------------------------------------------------------
function renderStatus(state: State): void {
  const data = state.data;
  if (!data) return;
  const when = `${ago(data.built_at)} · ${clockTime(data.built_at)}`;
  ui.status.classList.toggle("offline", state.offline);
  ui.status.textContent = state.offline ? `Sin conexión: mostrando el índice de las ${clockTime(data.built_at)}` : `Actualizado ${when}`;
  ui.status.title = `Build ${data.build_id}`;
}

function renderSources(data: IndexData): void {
  clear(ui.sources);
  for (const source of data.sources) {
    const status = source.status ?? "ok";
    const label = { ok: "correcta", partial: "parcial", failed: "falló", skipped: "omitida" }[status];
    ui.sources.appendChild(
      h("li", {}, `${SOURCE_LABELS[source.id] ?? source.id}: ${label}`, source.reason ? ` (${source.reason})` : ""),
    );
  }
}

// ---- tabs and filters ------------------------------------------------------------------------
function renderTabs(state: State): void {
  if (!ui.tabs.childElementCount) {
    for (const [id, label] of TABS) {
      ui.tabs.appendChild(
        h(
          "button",
          { type: "button", role: "tab", class: "tab", id: `tab-${id}`, "aria-controls": "view", "data-tab": id, onclick: () => selectTab(id) },
          label,
        ),
      );
    }
  }
  for (const button of ui.tabs.querySelectorAll<HTMLButtonElement>(".tab")) {
    const active = button.dataset.tab === state.tab && !state.query;
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active || (state.query && button.dataset.tab === "explore") ? 0 : -1;
  }
}

function fillOptions(select: HTMLSelectElement, entries: [string, string][]): void {
  const current = select.value;
  while (select.options.length > 1) select.remove(1);
  for (const [value, label] of entries) select.add(new Option(label, value));
  select.value = current;
}

function renderFilters(state: State): void {
  const data = state.data;
  if (!data) return;
  const types = Object.keys(data.totals.by_type).map((t) => [t, `${data.labels.types[t] ?? t} (${data.totals.by_type[t]})`] as [string, string]);
  const categories = Object.keys(data.totals.by_category).map((c) => [c, `${data.labels.categories[c] ?? c} (${data.totals.by_category[c]})`] as [string, string]);
  fillOptions(ui.type, types.sort((a, b) => a[1].localeCompare(b[1], "es")));
  fillOptions(ui.category, categories.sort((a, b) => a[1].localeCompare(b[1], "es")));
  ui.type.value = state.filters.type;
  ui.category.value = state.filters.category;
  ui.risk.value = state.filters.risk;
  ui.sort.value = state.filters.sort;
}

function selectTab(tab: Tab): void {
  listLimit = PAGE;
  ui.search.value = "";
  store.set({ tab, query: "" });
  ui.view.focus({ preventScroll: true });
}

// ---- main view -----------------------------------------------------------------------------------
function rowContext(state: State): RowContext {
  return {
    labels: state.data!.labels,
    sessionNew: state.sessionNew,
    selected: state.selected,
    onOpen: (id) => openItem(id),
  };
}

function newEngine(data: IndexData): SearchEngine {
  return new SearchEngine(data.items, { ...data.labels.types, ...data.labels.categories });
}

/** BM25 answers at once; the semantic layer joins when embeddings arrive (lazy download). */
function ensureEngine(state: State): SearchEngine | null {
  if (!state.data) return null;
  if (!engine) {
    const created = newEngine(state.data);
    engine = created;
    void cache.loadEmbeddings().then((embeddings) => {
      if (embeddings && engine === created) {
        created.attachEmbeddings(embeddings);
        if (store.state.query) renderKeepingPlace(store.state);
      }
    });
  }
  return engine;
}

// The toolbar is in the initial HTML so the list does not jump when the data arrives (CLS).
function syncToolbar(state: State): void {
  ui.toolbar.hidden = state.query.length > 0 || state.tab !== "explore";
}

function renderView(state: State): void {
  const data = state.data;
  if (!data) return;
  ui.view.setAttribute("aria-busy", "false");
  const searching = state.query.length > 0;
  syncToolbar(state);
  if (searching) {
    const result = ensureEngine(state)!.search(state.query);
    renderSearch(ui.view, result, rowContext(state), () => selectTab("gaps"));
    ui.count.textContent = "";
    return;
  }
  if (state.tab === "gaps") {
    renderGaps(ui.view, data, null);
    void cache.loadDemand().then((demand) => {
      if (store.state.tab === "gaps" && !store.state.query) renderGaps(ui.view, data, demand);
    });
    return;
  }
  const items = visibleItems(state);
  ui.count.textContent = `${items.length.toLocaleString("es")} repositorios`;
  if (!items.length) {
    clear(ui.view);
    ui.view.appendChild(h("p", { class: "notice" }, "Ningún repositorio cumple esos filtros."));
    return;
  }
  renderList(ui.view, items, rowContext(state), listLimit, "row", () => {
    listLimit += PAGE;
    renderView(store.state);
  });
}

/** Re-render without moving what the reader is looking at. */
function renderKeepingPlace(state: State): void {
  const rows = rowButtons(ui.view);
  const anchor = rows.find((b) => b.getBoundingClientRect().bottom > 0);
  const anchorId = anchor?.dataset.id;
  const anchorTop = anchor?.getBoundingClientRect().top ?? 0;
  const scrollY = window.scrollY;
  const focusedId = (document.activeElement as HTMLElement | null)?.dataset?.id;
  renderView(state);
  const again = anchorId ? rowButtons(ui.view).find((b) => b.dataset.id === anchorId) : undefined;
  if (again) window.scrollBy({ top: again.getBoundingClientRect().top - anchorTop });
  else window.scrollTo({ top: scrollY });
  if (focusedId) rowButtons(ui.view).find((b) => b.dataset.id === focusedId)?.focus({ preventScroll: true });
}

// ---- drawer --------------------------------------------------------------------------------------
function openItem(id: string): void {
  lastFocusedRow = id;
  store.set({ selected: id });
}

function closeDrawer(): void {
  store.set({ selected: null });
}

async function renderDrawerFor(state: State): Promise<void> {
  const item = state.selected ? state.byId.get(state.selected) : undefined;
  ui.layout.classList.toggle("with-drawer", !!item);
  for (const row of ui.view.querySelectorAll<HTMLLIElement>(".row")) {
    if (item && row.dataset.id === item.id) row.setAttribute("aria-current", "true");
    else row.removeAttribute("aria-current");
  }
  if (!item || !state.data) {
    ui.drawer.hidden = true;
    clear(ui.drawer);
    if (lastFocusedRow) rowButtons(ui.view).find((b) => b.dataset.id === lastFocusedRow)?.focus();
    return;
  }
  ui.drawer.hidden = false;
  const context = {
    labels: state.data.labels,
    siteUrl: state.data.site_url,
    byId: state.byId,
    onOpen: openItem,
    onClose: closeDrawer,
    announce,
  };
  renderDrawer(ui.drawer, item, null, null, context);
  ui.drawer.setAttribute("aria-busy", "true");
  const [detail, demand] = await Promise.all([
    cache.detail(item.category, item.id).catch(() => null),
    cache.loadDemand(),
  ]);
  if (store.state.selected !== item.id) return;
  renderDrawer(ui.drawer, item, detail, demand, context);
  ui.drawer.setAttribute("aria-busy", "false");
  ui.drawer.querySelector<HTMLElement>("#drawer-title")?.focus({ preventScroll: true });
}

// ---- reactions to state changes ------------------------------------------------------------------
store.subscribe((state, changed) => {
  history.replaceState(null, "", `${location.pathname}${toSearch(state)}`);
  if (changed.has("data")) {
    renderFilters(state);
    renderSources(state.data!);
  }
  if (changed.has("data") || changed.has("offline")) renderStatus(state);
  if (changed.has("tab") || changed.has("query") || changed.has("data")) renderTabs(state);
  const viewKeys: (keyof State)[] = ["tab", "query", "filters", "data", "sessionNew"];
  if (viewKeys.some((key) => changed.has(key))) {
    if (changed.has("data") && !changed.has("tab") && !changed.has("query")) renderKeepingPlace(state);
    else renderView(state);
  }
  if (changed.has("selected") || changed.has("data")) void renderDrawerFor(state);
});

// ---- input --------------------------------------------------------------------------------------
ui.search.value = store.state.query;
ui.search.addEventListener("input", () => {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => {
    listLimit = PAGE;
    store.set({ query: ui.search.value.slice(0, 200).trim() });
  }, 120);
});
ui.search.addEventListener("focus", () => void ensureEngine(store.state), { once: true });
ui.searchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  window.clearTimeout(searchTimer);
  store.set({ query: ui.search.value.slice(0, 200).trim() });
  rowButtons(ui.view)[0]?.focus();
});

ui.filters.addEventListener("change", () => {
  listLimit = PAGE;
  store.set({
    filters: {
      type: ui.type.value,
      category: ui.category.value,
      risk: ui.risk.value,
      sort: ui.sort.value as State["filters"]["sort"],
    },
  });
});

ui.filtersOpen.addEventListener("click", () => {
  ui.sheetBody.appendChild(ui.filters);
  ui.sheet.showModal();
});
ui.sheet.addEventListener("close", () => ui.toolbar.insertBefore(ui.filters, ui.filtersOpen));
ui.filtersClose.addEventListener("click", () => ui.sheet.close());

ui.tabs.addEventListener("keydown", (event) => {
  if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
  const buttons = [...ui.tabs.querySelectorAll<HTMLButtonElement>(".tab")];
  const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
  const next = buttons[(index + (event.key === "ArrowRight" ? 1 : buttons.length - 1)) % buttons.length];
  next?.focus();
});

document.addEventListener("keydown", (event) => {
  const target = event.target as HTMLElement;
  const typing = target.matches("input, textarea, select") || target.isContentEditable;
  if (event.key === "Escape") {
    if (store.state.selected) {
      event.preventDefault();
      closeDrawer();
    } else if (target === ui.search) {
      ui.search.blur();
    }
    return;
  }
  if (typing || event.altKey || event.ctrlKey || event.metaKey) return;
  if (event.key === "/") {
    event.preventDefault();
    ui.search.focus();
    ui.search.select();
    return;
  }
  if (event.key === "j" || event.key === "k") {
    const rows = rowButtons(ui.view);
    if (!rows.length) return;
    event.preventDefault();
    const index = rows.indexOf(document.activeElement as HTMLButtonElement);
    const next = event.key === "j" ? Math.min(rows.length - 1, index + 1) : Math.max(0, index - 1);
    rows[index === -1 ? 0 : next]?.focus();
    rows[index === -1 ? 0 : next]?.scrollIntoView({ block: "nearest" });
  }
});

// ---- startup and live updates --------------------------------------------------------------------
async function onUpdate(event: UpdateEvent): Promise<void> {
  if (event.kind === "offline") {
    store.set({ offline: true });
    return;
  }
  if (event.kind === "updated" && event.data) {
    cache.reset(event.data.files);
    // While a search is on screen, prepare the complete engine first so the results are
    // swapped once, in place, instead of twice (words now, meaning later).
    let next: SearchEngine | null = null;
    if (store.state.query) {
      next = newEngine(event.data);
      const embeddings = await cache.loadEmbeddings();
      if (embeddings) next.attachEmbeddings(embeddings);
    }
    engine = next;
    const added = store.replaceData(event.data);
    announce(added.length ? `Índice actualizado: ${added.length} repositorios nuevos.` : "Índice actualizado.");
    return;
  }
  store.set({ offline: false });
  renderStatus(store.state);
}

const updater = new Updater((event) => void onUpdate(event));

async function start(): Promise<void> {
  renderTabs(store.state);
  syncToolbar(store.state);
  try {
    const data = await updater.load();
    cache.reset(data.files);
    store.replaceData(data);
  } catch (error) {
    ui.toolbar.hidden = true;
    renderError(ui.view, error instanceof Error ? error.message : String(error));
    ui.status.textContent = "No se pudo cargar el índice";
    window.setTimeout(() => location.reload(), 5 * 60 * 1000);
    return;
  }
  updater.start();
  window.setInterval(() => renderStatus(store.state), 30_000);
  if (store.state.query) ensureEngine(store.state);
}

declare global {
  interface Window {
    __skillscope?: { check: () => Promise<UpdateEvent>; items: () => Item[] };
  }
}

// Hook used by the end-to-end tests to trigger the 5-minute check immediately.
window.__skillscope = { check: () => updater.check(), items: () => store.state.data?.items ?? [] };

void start();
