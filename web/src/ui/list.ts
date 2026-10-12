// Compact result rows. Rendering is chunked (60 rows at a time) so 6,000 items stay fast.
import { clear, h } from "../dom";
import { ago, compact, isNew, RISK_LABELS } from "../format";
import type { Item } from "../types";

export const PAGE = 60;

export interface RowContext {
  labels: { types: Record<string, string>; categories: Record<string, string> };
  sessionNew: Map<string, number>;
  selected: string | null;
  onOpen: (id: string) => void;
  now?: number;
}

function newBadge(item: Item, context: RowContext): HTMLElement | null {
  const now = context.now ?? Date.now();
  const addedNow = context.sessionNew.get(item.id);
  const fresh = isNew(item.first_seen, now) || (addedNow !== undefined && now - addedNow < 3_600_000);
  return fresh ? h("span", { class: "new" }, "nuevo") : null;
}

export function row(item: Item, context: RowContext, index: number, prefix = "row"): HTMLLIElement {
  const titleId = `${prefix}-title-${index}`;
  const metaId = `${prefix}-meta-${index}`;
  const typeLabel = context.labels.types[item.type] ?? item.type;
  const categoryLabel = context.labels.categories[item.category] ?? item.category;
  const button = h(
    "button",
    {
      type: "button",
      class: "row-main",
      "aria-labelledby": titleId,
      "aria-describedby": metaId,
      "data-id": item.id,
      onclick: () => context.onOpen(item.id),
    },
    h("span", { class: "score", title: `Puntaje ${item.score} de 100` }, String(item.score)),
    h(
      "span",
      { class: "title" },
      h("span", { class: "repo", id: titleId }, h("span", { class: "owner" }, `${item.owner}/`), item.name),
      h("span", { class: "tag" }, typeLabel),
      h("span", { class: "tag" }, categoryLabel),
      newBadge(item, context),
    ),
    h("span", { class: "summary" }, item.summary),
    h(
      "span",
      { class: "meta", id: metaId },
      h("span", {}, `★ ${compact(item.stars)}`),
      h("span", { class: `risk risk-${item.risk.level}` }, RISK_LABELS[item.risk.level]),
      item.pushed_at ? h("span", {}, `actividad ${ago(item.pushed_at, context.now)}`) : null,
      item.sample ? h("span", {}, "ejemplo ficticio") : null,
    ),
  );
  return h(
    "li",
    { class: "row", "data-id": item.id, "aria-current": context.selected === item.id ? "true" : null },
    button,
  );
}

/** Render the first ``limit`` items; "Mostrar más" asks the owner to raise the limit, so
 * the limit survives live updates and the reader never loses their place. */
export function renderList(
  container: HTMLElement,
  items: Item[],
  context: RowContext,
  limit = PAGE,
  prefix = "row",
  onMore?: () => void,
): void {
  clear(container);
  if (!items.length) return;
  const list = h("ul", { class: "list", "aria-label": "Repositorios" });
  const shown = Math.min(limit, items.length);
  for (let i = 0; i < shown; i++) list.appendChild(row(items[i]!, context, i, prefix));
  container.appendChild(list);
  if (shown < items.length && onMore) {
    const more = h(
      "button",
      {
        type: "button",
        class: "button more",
        onclick: () => {
          onMore();
          const next = container.querySelectorAll<HTMLButtonElement>(".row-main")[shown];
          next?.focus({ preventScroll: true });
        },
      },
      `Mostrar ${Math.min(PAGE, items.length - shown)} más (${items.length - shown} restantes)`,
    );
    container.appendChild(more);
  }
}

/** Rows currently on screen, in order (used by the j/k keyboard navigation). */
export function rowButtons(root: ParentNode): HTMLButtonElement[] {
  return [...root.querySelectorAll<HTMLButtonElement>(".row-main")];
}
