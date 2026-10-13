import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { externalLink, h, safeUrl } from "../src/dom";
import { ago, isNew } from "../src/format";
import { initialState, Store, toSearch, visibleItems } from "../src/store";
import type { Detail } from "../src/types";
import { renderDrawer } from "../src/ui/drawer";
import { renderList, rowButtons } from "../src/ui/list";
import { renderGaps, renderSearch } from "../src/ui/views";
import { index, item } from "./fixtures";

const NOW = Date.parse("2026-10-12T12:00:00Z");
const hostile = '<img src=x onerror="alert(1)">';

describe("safe DOM", () => {
  it("renders third-party text as text, never as markup", () => {
    const el = h("p", {}, hostile);
    expect(el.textContent).toBe(hostile);
    expect(el.querySelector("img")).toBeNull();
  });

  it("drops non-http links and isolates external ones", () => {
    expect(safeUrl("javascript:alert(1)")).toBeNull();
    expect(safeUrl("data:text/html,x")).toBeNull();
    const link = externalLink("https://github.com/a/b", "repo");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(externalLink("javascript:x", "bad").tagName).toBe("SPAN");
  });

  it("no source file uses HTML sinks (innerHTML, outerHTML, insertAdjacentHTML, eval…)", () => {
    const root = resolve(process.cwd(), "src");
    const files: string[] = [];
    const walk = (dir: string): void => {
      for (const name of readdirSync(dir)) {
        const path = join(dir, name);
        if (statSync(path).isDirectory()) walk(path);
        else if (path.endsWith(".ts")) files.push(path);
      }
    };
    walk(root);
    expect(files.length).toBeGreaterThan(5);
    for (const file of files) {
      const code = readFileSync(file, "utf-8");
      expect(code, file).not.toMatch(/\.(innerHTML|outerHTML)\s*=|insertAdjacentHTML|document\.write|\beval\(|new Function\(/);
    }
  });
});

describe("format", () => {
  it("relative times and the one-hour 'nuevo' window", () => {
    expect(ago("2026-10-12T11:57:00Z", NOW)).toBe("hace 3 min");
    expect(ago("2026-10-12T10:00:00Z", NOW)).toBe("hace 2 h");
    expect(ago("2026-10-11T11:00:00Z", NOW)).toBe("hace 1 día");
    expect(ago("2026-10-12T12:00:30Z", NOW)).toBe("hace menos de 1 min");
    expect(isNew("2026-10-12T11:30:00Z", NOW)).toBe(true);
    expect(isNew("2026-10-12T10:30:00Z", NOW)).toBe(false);
    expect(isNew("not a date", NOW)).toBe(false);
  });
});

describe("store", () => {
  it("parses and writes the URL state", () => {
    const state = initialState("?q=hola&tab=gaps&type=skill&risk=2&sort=stars&r=a%2Fb&cat=testing");
    expect(state.tab).toBe("gaps");
    expect(state.filters).toEqual({ type: "skill", category: "testing", risk: "2", sort: "stars" });
    expect(toSearch(state)).toBe("?q=hola&tab=gaps&type=skill&cat=testing&risk=2&sort=stars&r=a%2Fb");
    expect(initialState("?tab=evil&sort=evil").tab).toBe("explore");
  });

  it("marks repositories that arrive with a new build", () => {
    const store = new Store(initialState(""));
    expect(store.replaceData(index([item()]), NOW)).toEqual([]);
    const listener = vi.fn();
    store.subscribe(listener);
    const added = store.replaceData(index([item(), item({ id: "acme/new" })], { build_id: "b2" }), NOW);
    expect(added).toEqual(["acme/new"]);
    expect(store.state.sessionNew.get("acme/new")).toBe(NOW);
    expect(listener).toHaveBeenCalledOnce();
  });

  it("filters and sorts the explore view and resolves list tabs", () => {
    const items = [
      item({ id: "a/1", score: 10, stars: 500, type: "plugin" }),
      item({ id: "a/2", score: 90, stars: 5, risk: { level: 3, penalty: 20, flags: [] } }),
    ];
    const store = new Store(initialState(""));
    store.replaceData(index(items, { lists: { ...index([]).lists, riskiest: ["a/2", "missing/x"] } }));
    expect(visibleItems(store.state).map((i) => i.id)).toEqual(["a/2", "a/1"]);
    store.set({ filters: { ...store.state.filters, sort: "stars" } });
    expect(visibleItems(store.state).map((i) => i.id)).toEqual(["a/1", "a/2"]);
    store.set({ filters: { ...store.state.filters, type: "plugin" } });
    expect(visibleItems(store.state).map((i) => i.id)).toEqual(["a/1"]);
    store.set({ tab: "riskiest" });
    expect(visibleItems(store.state).map((i) => i.id)).toEqual(["a/2"]);
  });
});

const context = {
  labels: { types: { skill: "Skill suelta" }, categories: { development: "Desarrollo" } },
  sessionNew: new Map<string, number>(),
  selected: null,
  onOpen: vi.fn(),
  now: NOW,
};

describe("list", () => {
  it("renders rows, the 'nuevo' badge and a load-more button", () => {
    const container = document.createElement("div");
    const items = Array.from({ length: 70 }, (_, i) => item({ id: `o/r${i}`, name: hostile, first_seen: i === 0 ? "2026-10-12T11:50:00Z" : "2026-01-01T00:00:00Z" }));
    const onMore = vi.fn();
    renderList(container, items, context, 60, "row", onMore);
    expect(rowButtons(container)).toHaveLength(60);
    expect(container.querySelectorAll(".new")).toHaveLength(1);
    expect(container.querySelector("img")).toBeNull();
    (container.querySelector(".more") as HTMLButtonElement).click();
    expect(onMore).toHaveBeenCalled();
    rowButtons(container)[1]!.click();
    expect(context.onOpen).toHaveBeenCalledWith("o/r1");
  });
});

const detail: Detail = {
  id: "acme/tool",
  what: "Qué hace.",
  when: ["Cuando haga falta."],
  install: { kind: "marketplace", steps: [{ label: "Agregar", command: "/plugin marketplace add acme/tool" }, { label: "Instalar", command: "/plugin install t@m" }], note: "nota", one_liner: "claude plugin marketplace add acme/tool && claude plugin install t@m" },
  risks: [{ id: "prompt-injection", severity: "high", penalty: 10, title: "Inyección", why: "por qué", evidence: [{ path: "SKILL.md", line: 3, snippet: hostile }] }],
  score: { total: 40, components: [{ id: "quality", label: "Calidad", points: 20, max: 25, factors: [{ id: "valid", label: "Formato", value: "1 de 1", points: 6, max: 6 }] }, { id: "risk", label: "Riesgo", points: -10, max: 25, factors: [] }] },
  artifacts: [{ kind: "skill", path: "a/SKILL.md", name: "a", valid: false, issues: ["name-format"] }],
  tools: [],
  readme_lang: "en",
  collections: ["acme/list"],
  co: ["acme/other"],
  topics: [],
  category_terms: [],
  answers: ["stackexchange:1"],
  signals: { stars: [1, null, 3], mentions: { hackernews: 2 } },
  links: { repo: "https://github.com/acme/tool", license: null },
  archived: false,
  created_at: "2026-01-01T00:00:00Z",
};

describe("drawer", () => {
  it("answers the four questions and keeps evidence as text", () => {
    const root = document.createElement("aside");
    const target = item({ risk: { level: 3, penalty: 10, flags: ["prompt-injection"] } });
    const demand = {
      build_id: "b",
      attribution: "CC BY-SA",
      items: [{ key: "stackexchange:1", source: "stackexchange", title: "¿Cómo?", url: "https://stackoverflow.com/q/1", author: "Ana", author_url: null, created_at: "", answered: false, tags: [], topic: null }],
      topics: [],
      gaps: [],
      categories: [],
    };
    renderDrawer(root, target, detail, demand, {
      labels: context.labels,
      siteUrl: "https://example.test/",
      byId: new Map([["acme/other", item({ id: "acme/other" })]]),
      onOpen: vi.fn(),
      onClose: vi.fn(),
      announce: vi.fn(),
    });
    const text = root.textContent ?? "";
    for (const heading of ["Qué hace", "Cuándo usarla", "Cómo se instala", "Qué riesgos tiene", "Puntaje 40 de 100", "Señales", "Responde a preguntas reales", "Insignia para tu README"]) {
      expect(text).toContain(heading);
    }
    expect(root.querySelector("img")).toBeNull();
    expect(text).toContain(hostile);
    expect(root.querySelectorAll(".copy")).toHaveLength(4);
    expect((root.querySelector(".bar-fill") as HTMLElement).style.width).toBe("80%");
    expect(root.querySelector("svg.spark")?.getAttribute("aria-label")).toContain("de 1 a 3");
  });

  it("never presents the offline demo questions as real Stack Overflow posts", () => {
    const root = document.createElement("aside");
    const demand = {
      build_id: "b",
      attribution: "Preguntas ficticias de ejemplo",
      sample: true,
      items: [{ key: "stackexchange:1", source: "stackexchange", title: "¿Cómo?", url: "https://example.com/q/1", author: "dev_sample_1", author_url: null, created_at: "", answered: false, tags: [], topic: null }],
      topics: [],
      gaps: [],
      categories: [],
    };
    renderDrawer(root, item(), detail, demand, {
      labels: context.labels,
      siteUrl: "https://example.test/",
      byId: new Map(),
      onOpen: vi.fn(),
      onClose: vi.fn(),
      announce: vi.fn(),
    });
    const text = root.textContent ?? "";
    expect(text).toContain("Responde a preguntas (ejemplo ficticio)");
    expect(text).not.toContain("Stack Overflow");
  });

  it("degrades gracefully without detail", () => {
    const root = document.createElement("aside");
    renderDrawer(root, item({ sample: true }), null, null, {
      labels: context.labels,
      siteUrl: "https://example.test/",
      byId: new Map(),
      onOpen: vi.fn(),
      onClose: vi.fn(),
      announce: vi.fn(),
    });
    expect(root.textContent).toContain("No se pudo cargar la ficha completa");
  });
});

describe("views", () => {
  it("turns an empty search into an opportunity", () => {
    const container = document.createElement("div");
    renderSearch(container, { query: "cobol", exact: [], similar: [], together: [], semantic: true, elapsedMs: 1 }, context, vi.fn());
    expect(container.textContent).toContain("Nadie ha publicado una skill para esto");
    expect(container.querySelector('a[href*="template"]')).not.toBeNull();
  });

  it("lists gaps with attributed example questions", () => {
    const container = document.createElement("div");
    renderGaps(container, index([]), {
      build_id: "b",
      attribution: "Stack Overflow · CC BY-SA 4.0",
      items: [{ key: "stackexchange:9", source: "stackexchange", title: "COBOL?", url: "https://stackoverflow.com/q/9", author: "Ana", author_url: "https://stackoverflow.com/users/1", created_at: "", answered: false, tags: [], topic: "cobol" }],
      topics: [],
      gaps: [{ id: "cobol", topic: "cobol", label: "cobol, mainframe", keywords: [], category: "development", demand: 2, questions: 2, examples: ["stackexchange:9"] }],
      categories: [],
    });
    expect(container.textContent).toContain("cobol, mainframe");
    expect(container.textContent).toContain("CC BY-SA 4.0");
    expect(container.querySelector('a[href="https://stackoverflow.com/q/9"]')?.getAttribute("rel")).toBe("noopener noreferrer");
  });
});
