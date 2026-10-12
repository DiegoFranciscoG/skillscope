// Search results (three blocks), the gaps view and empty states.
import { append, clear, externalLink, h } from "../dom";
import type { SearchResult } from "../search/hybrid";
import type { DemandData, IndexData } from "../types";
import { renderList, type RowContext } from "./list";

const TEMPLATE_URL = "https://github.com/anthropics/skills/tree/main/template";
const SKILLS_DOCS = "https://code.claude.com/docs/en/skills";
const REQUEST_URL = "https://github.com/DiegoFranciscoG/skillscope/issues/new?template=skill-request.yml";

function block(title: string, note: string, content: HTMLElement): HTMLElement {
  return h("section", { class: "block" }, h("h2", {}, title), h("p", { class: "block-note" }, note), content);
}

export function renderSearch(container: HTMLElement, result: SearchResult, context: RowContext, onGaps: () => void): void {
  clear(container);
  if (!result.exact.length && !result.similar.length) {
    append(
      container,
      h(
        "div",
        { class: "empty" },
        h("h2", {}, "Nadie ha publicado una skill para esto todavía"),
        h(
          "p",
          {},
          "Es una oportunidad: créala con la plantilla oficial y publícala en GitHub; Skillscope la encontrará en las próximas actualizaciones.",
        ),
        h(
          "p",
          {},
          externalLink(TEMPLATE_URL, "Plantilla para crear una skill"),
          " · ",
          externalLink(SKILLS_DOCS, "Documentación de skills"),
          " · ",
          externalLink(REQUEST_URL, "Pedir que alguien la construya"),
          " · ",
          h("a", { href: "?tab=gaps", onclick: (e: Event) => (e.preventDefault(), onGaps()) }, "Ver huecos del ecosistema"),
        ),
      ),
    );
    return;
  }
  const exact = h("div", {});
  const similar = h("div", {});
  const together = h("div", {});
  renderList(exact, result.exact.map((hit) => hit.item), context, 8, "exact");
  renderList(similar, result.similar.map((hit) => hit.item), context, 8, "similar");
  renderList(together, result.together, context, 6, "together");
  const semanticNote = result.semantic ? "" : " (búsqueda por palabras; la semántica carga en segundo plano)";
  if (result.exact.length) {
    append(container, block("Resuelve exactamente eso", `Coinciden las palabras y el sentido${semanticNote}.`, exact));
  } else {
    append(container, h("p", { class: "notice" }, "No hay una coincidencia exacta; estas son las más parecidas."));
  }
  if (result.similar.length) append(container, block("Se le parece", "Resuelven algo cercano o parte del problema.", similar));
  if (result.together.length) {
    append(container, block("Se usan junto con eso", "Aparecen en los mismos marketplaces y listas que los resultados.", together));
  }
}

export function renderGaps(container: HTMLElement, data: IndexData, demand: DemandData | null): void {
  clear(container);
  const labels = data.labels.categories;
  if (!demand) {
    append(container, h("p", { class: "notice" }, "No se pudo cargar la demanda. Reintenta en unos minutos."));
    return;
  }
  const byKey = new Map(demand.items.map((q) => [q.key, q]));
  const gaps = h("ul", { class: "cards" });
  for (const gap of demand.gaps) {
    const examples = gap.examples.map((key) => byKey.get(key)).filter((q) => q !== undefined);
    gaps.appendChild(
      h(
        "li",
        { class: "card" },
        h("h3", {}, gap.label),
        h("p", { class: "small muted" }, `${labels[gap.category] ?? gap.category} · ${gap.questions} preguntas · demanda ${gap.demand}`),
        examples.length
          ? h(
              "ul",
              { class: "small" },
              ...examples.map((q) =>
                h("li", {}, externalLink(q.url, q.title), h("span", { class: "attribution" }, " · ", externalLink(q.author_url, q.author))),
              ),
            )
          : null,
        h("p", { class: "small" }, externalLink(TEMPLATE_URL, "Crear esta skill")),
      ),
    );
  }
  const needed = h(
    "table",
    { class: "table" },
    h("caption", { class: "visually-hidden" }, "Categorías más necesarias"),
    h(
      "thead",
      {},
      h(
        "tr",
        {},
        h("th", { scope: "col" }, "Categoría"),
        h("th", { scope: "col", class: "num" }, "Demanda"),
        h("th", { scope: "col", class: "num" }, "Oferta (puntaje ≥ 50)"),
        h("th", { scope: "col", class: "num" }, "Necesidad"),
      ),
    ),
    h(
      "tbody",
      {},
      ...data.lists.most_needed.map((row) =>
        h(
          "tr",
          {},
          h("td", {}, labels[row.category] ?? row.category),
          h("td", { class: "num" }, String(row.demand)),
          h("td", { class: "num" }, String(row.supply)),
          h("td", { class: "num" }, String(row.ratio)),
        ),
      ),
    ),
  );
  append(
    container,
    h(
      "section",
      { class: "gaps" },
      h("h2", {}, "Huecos del ecosistema"),
      h(
        "p",
        { class: "block-note" },
        "Temas que la gente pregunta y nadie ha resuelto con una skill o plugin de buena calidad. Se calculan agrupando preguntas sin respuesta y buscando repos que cubran sus etiquetas.",
      ),
      demand.gaps.length ? gaps : h("p", { class: "notice" }, "Por ahora no hay temas con demanda alta y oferta vacía."),
    ),
    block("Más necesarias por categoría", "Demanda ÷ (1 + oferta). Cuanto mayor, más falta hace.", needed),
    h("p", { class: "attribution" }, demand.attribution),
  );
}

export function renderError(container: HTMLElement, message: string): void {
  clear(container);
  append(
    container,
    h(
      "div",
      { class: "empty" },
      h("h2", {}, "No se pudo cargar el índice"),
      h("p", {}, message),
      h("p", {}, "Revisa tu conexión; la página reintentará sola en unos minutos."),
    ),
  );
}
