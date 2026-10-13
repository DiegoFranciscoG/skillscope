// "Más allá del índice": when a search finds little among the analyzed repositories, look in the
// discovery queue (thousands of repositories not analyzed yet) and, if the reader asks, on GitHub
// itself. Every result can be sent for a priority analysis through an issue form.
import { append, clear, externalLink, h } from "../dom";
import { ago, compact } from "../format";
import type { LiveResult } from "../github-live";
import { CandidateIndex } from "../search/candidates";
import type { Candidate } from "../types";

export const REQUEST_ANALYSIS =
  "https://github.com/DiegoFranciscoG/skillscope/issues/new?template=skill-request.yml";

export interface BeyondDeps {
  loadCandidates: () => Promise<Candidate[] | null>;
  searchGitHub: (query: string) => Promise<LiveResult>;
  inIndex: (id: string) => boolean;
  onOpen: (id: string) => void;
  now: number;
}

/** Prefilled issue form: the pipeline reads it and analyzes the repository first. */
export function requestUrl(id: string): string {
  const params = new URLSearchParams({ title: `Analizar: ${id}`, repository: id });
  return `${REQUEST_ANALYSIS}&${params.toString()}`;
}

interface Found {
  id: string;
  description: string;
  stars: number;
  pushedAt: string | null;
  topics?: string[];
}

function foundRow(found: Found, deps: BeyondDeps): HTMLLIElement {
  const analyzed = deps.inIndex(found.id);
  const action = analyzed
    ? h("a", { href: `?r=${encodeURIComponent(found.id)}`, onclick: (e: Event) => (e.preventDefault(), deps.onOpen(found.id)) }, "Ver ficha en Skillscope")
    : externalLink(requestUrl(found.id), "Pedir análisis prioritario");
  return h(
    "li",
    { class: "found" },
    h("span", { class: "found-title" }, externalLink(`https://github.com/${found.id}`, found.id)),
    found.description ? h("span", { class: "summary" }, found.description) : null,
    h(
      "span",
      { class: "meta" },
      h("span", {}, `★ ${compact(found.stars)}`),
      found.pushedAt ? h("span", {}, `actividad ${ago(found.pushedAt, deps.now)}`) : null,
      found.topics?.length ? h("span", {}, found.topics.slice(0, 4).join(" · ")) : null,
      h("span", {}, analyzed ? "ya analizado" : "sin analizar"),
      action,
    ),
  );
}

function section(title: string, note: string, ...children: (Node | null)[]): HTMLElement {
  return h("section", { class: "block beyond" }, h("h2", {}, title), h("p", { class: "block-note" }, note), ...children);
}

let indexCache: { source: Candidate[]; index: CandidateIndex } | null = null;

function candidateIndex(items: Candidate[]): CandidateIndex {
  if (indexCache?.source !== items) indexCache = { source: items, index: new CandidateIndex(items) };
  return indexCache.index;
}

/** Appends the queue and live-search sections; stale async results land in detached nodes. */
export function renderBeyond(container: HTMLElement, query: string, deps: BeyondDeps): void {
  const queue = h("div", {}, h("p", { class: "notice" }, "Buscando entre los repositorios en cola de análisis…"));
  append(
    container,
    section(
      "Encontrados por Skillscope, aún sin analizar",
      "Repositorios que el descubrimiento ya encontró y esperan su análisis. Todavía no tienen puntaje ni revisión de riesgos.",
      queue,
    ),
  );
  void deps.loadCandidates().then((items) => {
    clear(queue);
    const hits = items ? candidateIndex(items).search(query) : [];
    if (!hits.length) {
      append(queue, h("p", { class: "notice" }, "Nada parecido en la cola por ahora."));
      return;
    }
    append(
      queue,
      h(
        "ul",
        { class: "found-list" },
        ...hits.map(({ candidate }) =>
          foundRow({ id: candidate.id, description: candidate.d, stars: candidate.s, pushedAt: candidate.p, topics: candidate.t }, deps),
        ),
      ),
    );
  });

  const live = h("div", {});
  const button = h(
    "button",
    {
      type: "button",
      class: "button",
      onclick: () => {
        button.disabled = true;
        clear(live);
        append(live, h("p", { class: "notice", role: "status" }, "Consultando GitHub…"));
        void deps.searchGitHub(query).then((result) => {
          clear(live);
          button.disabled = false;
          if (!result.ok) {
            append(live, h("p", { class: "notice", role: "status" }, result.reason));
            return;
          }
          if (!result.repos.length) {
            append(live, h("p", { class: "notice", role: "status" }, "GitHub tampoco tiene repositorios para esta búsqueda."));
            return;
          }
          const origin = result.cached ? " (guardado de tu búsqueda anterior)" : "";
          append(
            live,
            h("p", { class: "notice", role: "status" }, `${result.repos.length} repositorios en GitHub${origin}. Revísalos antes de instalarlos: no están analizados.`),
            h(
              "ul",
              { class: "found-list" },
              ...result.repos.map((repo) => foundRow({ id: repo.id, description: repo.description, stars: repo.stars, pushedAt: repo.pushedAt }, deps)),
            ),
          );
        });
      },
    },
    "Buscar en GitHub ahora",
  );
  append(
    container,
    section(
      "Buscar en todo GitHub",
      "Envía tu búsqueda a la API pública de GitHub, sin cuenta ni cookies, solo si pulsas el botón.",
      button,
      live,
    ),
  );
}
