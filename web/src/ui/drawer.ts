// Detail panel: the four questions (qué hace, cuándo usarla, cómo se instala, qué riesgos
// tiene), the score breakdown and the signals. Opens beside the list so items can be compared.
import { append, clear, externalLink, h } from "../dom";
import { CAUSE_LABELS, compact, longDate, RISK_LABELS, SEVERITY_LABELS, SOURCE_LABELS } from "../format";
import type { DemandData, Detail, Item } from "../types";
import { sparkline } from "./sparkline";

export interface DrawerContext {
  labels: { types: Record<string, string>; categories: Record<string, string> };
  siteUrl: string;
  byId: Map<string, Item>;
  onOpen: (id: string) => void;
  onClose: () => void;
  announce: (text: string) => void;
}

const TEMPLATE_URL = "https://github.com/anthropics/skills/tree/main/template";

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function copyBlock(text: string, label: string, context: DrawerContext): HTMLElement {
  const button = h("button", { type: "button", class: "button copy", "aria-label": `Copiar: ${label}` }, "Copiar");
  button.addEventListener("click", () => {
    void copyText(text).then((ok) => {
      button.textContent = ok ? "Copiado" : "Selecciónalo";
      context.announce(ok ? "Comando copiado al portapapeles" : "No se pudo copiar; selecciona el texto");
      window.setTimeout(() => (button.textContent = "Copiar"), 2000);
    });
  });
  return h("div", { class: "code" }, h("code", {}, text), button);
}

function section(title: string, ...children: (Node | null)[]): HTMLElement {
  return h("section", {}, h("h3", {}, title), ...children);
}

function installSection(detail: Detail, context: DrawerContext): HTMLElement {
  const install = detail.install;
  const nodes: (Node | null)[] = [];
  if (!install.steps.length) {
    nodes.push(h("p", {}, install.note || "Sin comando verificable: sigue las instrucciones del README."));
  }
  for (const step of install.steps) {
    nodes.push(h("div", { class: "step" }, h("span", { class: "step-label" }, step.label), copyBlock(step.command, step.label, context)));
  }
  if (install.one_liner && install.steps.length > 1) {
    nodes.push(
      h(
        "div",
        { class: "step" },
        h("span", { class: "step-label" }, "Todo en un paso desde la terminal"),
        copyBlock(install.one_liner, "comando completo", context),
      ),
    );
  }
  if (install.note && install.steps.length) nodes.push(h("p", { class: "small muted" }, install.note));
  if (install.steps.length) {
    nodes.push(h("p", { class: "small muted" }, "Comandos para bash o zsh; en Windows usa Git Bash o WSL. Revisa el código antes de instalar."));
  }
  return section("Cómo se instala", ...nodes);
}

function risksSection(item: Item, detail: Detail): HTMLElement {
  if (!detail.risks.length) {
    return section(
      "Qué riesgos tiene",
      h("p", {}, "No se detectaron banderas de riesgo en los archivos analizados."),
      h("p", { class: "small muted" }, "Que no haya banderas no garantiza seguridad: el análisis es automático."),
    );
  }
  const flags = detail.risks.map((flag) =>
    h(
      "div",
      { class: `flag ${flag.severity}` },
      h("strong", {}, `${flag.title} · severidad ${SEVERITY_LABELS[flag.severity] ?? flag.severity} (−${flag.penalty})`),
      h("span", { class: "small" }, flag.why),
      flag.evidence.length
        ? h(
            "ul",
            { class: "evidence" },
            ...flag.evidence.map((e) => h("li", {}, h("span", { class: "muted" }, `${e.path}:${e.line} `), h("code", {}, e.snippet))),
          )
        : null,
    ),
  );
  return section(
    "Qué riesgos tiene",
    h("p", { class: `risk risk-${item.risk.level}` }, `${RISK_LABELS[item.risk.level]} · penalización ${item.risk.penalty} de 25`),
    ...flags,
  );
}

function scoreSection(detail: Detail): HTMLElement {
  const bars = h("div", { class: "bars" });
  for (const component of detail.score.components) {
    const negative = component.points < 0;
    const fill = h("div", { class: negative ? "bar-fill negative" : "bar-fill" });
    fill.style.width = `${Math.min(100, (Math.abs(component.points) / (component.max || 1)) * 100)}%`;
    const factors = h(
      "table",
      { class: "factors" },
      h("caption", { class: "visually-hidden" }, `Factores de ${component.label}`),
      h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Factor"), h("th", { scope: "col" }, "Medido"), h("th", { scope: "col" }, "Puntos"))),
      h(
        "tbody",
        {},
        ...component.factors.map((f) =>
          h("tr", {}, h("td", {}, f.label), h("td", {}, f.value), h("td", {}, f.max ? `${f.points} / ${f.max}` : String(f.points))),
        ),
      ),
    );
    append(
      bars,
      h(
        "div",
        { class: "bar" },
        h("span", {}, component.label),
        h("span", { class: "points" }, negative ? `${component.points}` : `${component.points} / ${component.max}`),
        h("div", { class: "bar-track" }, fill),
        h("details", { class: "small" }, h("summary", {}, "Ver factores"), factors),
      ),
    );
  }
  return section(
    `Puntaje ${detail.score.total} de 100`,
    bars,
    h(
      "p",
      { class: "small" },
      externalLink("https://github.com/DiegoFranciscoG/skillscope/blob/main/docs/algoritmo.md", "Cómo se calcula cada factor"),
    ),
  );
}

function signalsSection(item: Item, detail: Detail): HTMLElement {
  const stars = detail.signals.stars;
  const known = stars.filter((v): v is number => v !== null);
  const label = known.length
    ? `Estrellas en 30 días: de ${known[0]} a ${known[known.length - 1]}`
    : "Sin historial de estrellas todavía";
  const mentions = Object.entries(detail.signals.mentions);
  return section(
    "Señales",
    sparkline(stars, label),
    h("p", { class: "small muted" }, label),
    h(
      "p",
      { class: "small" },
      mentions.length
        ? `Menciones (180 días): ${mentions.map(([s, n]) => `${SOURCE_LABELS[s] ?? s} ${n}`).join(" · ")}`
        : "Sin menciones públicas detectadas.",
      ` · ★ ${compact(item.stars)} · forks ${compact(item.forks)}`,
    ),
  );
}

function repoLinks(ids: string[], context: DrawerContext): HTMLElement {
  const list = h("ul", {});
  for (const id of ids) {
    const known = context.byId.get(id);
    list.appendChild(
      h(
        "li",
        {},
        known
          ? h("a", { href: `?r=${encodeURIComponent(id)}`, onclick: (e: Event) => (e.preventDefault(), context.onOpen(id)) }, id)
          : h("span", {}, id),
      ),
    );
  }
  return list;
}

function answersSection(detail: Detail, demand: DemandData | null): HTMLElement | null {
  if (!detail.answers.length || !demand) return null;
  const byKey = new Map(demand.items.map((q) => [q.key, q]));
  const questions = detail.answers.map((key) => byKey.get(key)).filter((q) => q !== undefined);
  if (!questions.length) return null;
  const source = demand.sample ? ", pregunta ficticia de ejemplo" : " en Stack Overflow, CC BY-SA 4.0";
  return section(
    demand.sample ? "Responde a preguntas (ejemplo ficticio)" : "Responde a preguntas reales",
    h(
      "ul",
      {},
      ...questions.map((q) =>
        h("li", {}, externalLink(q.url, q.title), h("span", { class: "attribution" }, " · ", externalLink(q.author_url, q.author), source)),
      ),
    ),
  );
}

export function renderDrawer(
  root: HTMLElement,
  item: Item,
  detail: Detail | null,
  demand: DemandData | null,
  context: DrawerContext,
): void {
  clear(root);
  const close = h("button", { type: "button", class: "button close", "aria-label": "Cerrar detalle", onclick: context.onClose }, "✕");
  const head = h(
    "div",
    { class: "drawer-head" },
    h("div", {}, h("h2", { id: "drawer-title", tabindex: "-1" }, `${item.owner}/${item.name}`)),
    close,
  );
  const badges = h(
    "div",
    { class: "badges" },
    h("span", { class: "tag" }, context.labels.types[item.type] ?? item.type),
    h("span", { class: "tag" }, context.labels.categories[item.category] ?? item.category),
    h("span", { class: "tag" }, CAUSE_LABELS[item.cause] ?? item.cause),
    h("span", { class: "tag" }, `puntaje ${item.score}`),
  );
  append(root, head, badges);

  if (!detail) {
    append(root, h("p", { class: "notice" }, "No se pudo cargar la ficha completa. Se reintentará con la próxima actualización."));
    return;
  }

  const repoLink = detail.links.repo
    ? externalLink(detail.links.repo, "Ver el repositorio en GitHub")
    : h("span", { class: "muted" }, "Repositorio ficticio de ejemplo: no enlaza a GitHub.");
  append(
    root,
    section("Qué hace", h("p", {}, detail.what), h("p", { class: "small" }, repoLink, item.license ? ` · licencia ${item.license}` : " · sin licencia")),
    section("Cuándo usarla", h("ul", {}, ...detail.when.map((w) => h("li", {}, w)))),
    installSection(detail, context),
    risksSection(item, detail),
    scoreSection(detail),
    signalsSection(item, detail),
    answersSection(detail, demand),
  );
  if (detail.collections.length) append(root, section("Aparece en", repoLinks(detail.collections, context)));
  if (detail.co.length) append(root, section("Se usa junto con", repoLinks(detail.co, context)));
  if (detail.artifacts.length) {
    const invalid = detail.artifacts.filter((a) => !a.valid);
    append(
      root,
      section(
        "Formato",
        h("p", { class: "small" }, `${detail.artifacts.length - invalid.length} de ${detail.artifacts.length} archivos válidos según la especificación.`),
        invalid.length
          ? h("ul", { class: "small" }, ...invalid.slice(0, 8).map((a) => h("li", {}, h("code", {}, a.path), ` — ${a.issues.join(", ")}`)))
          : null,
      ),
    );
  }
  if (!item.sample) {
    const page = `${context.siteUrl}s/${item.owner}/${item.name}/`;
    const badge = `[![Listado en Skillscope · puntaje ${item.score}](${context.siteUrl}badge/${item.owner}/${item.name}.svg)](${page})`;
    append(
      root,
      section(
        "Insignia para tu README",
        copyBlock(badge, "insignia en Markdown", context),
        h("p", { class: "small" }, externalLink(page, "Página pública de este repositorio")),
      ),
    );
  }
  append(
    root,
    h(
      "p",
      { class: "small muted" },
      detail.created_at ? `Creado el ${longDate(detail.created_at)}. ` : "",
      `¿No encuentras algo parecido? `,
      externalLink(TEMPLATE_URL, "Crea una skill con la plantilla oficial"),
      ".",
    ),
  );
}
