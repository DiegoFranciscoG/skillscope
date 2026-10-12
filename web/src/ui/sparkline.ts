// Accessible SVG sparkline built with createElementNS (no markup strings).
import { svg } from "../dom";

export function sparkline(values: (number | null)[], label: string): SVGElement {
  const width = 300;
  const height = 48;
  const known = values.map((v, i) => [i, v] as const).filter((p): p is readonly [number, number] => p[1] !== null);
  const root = svg("svg", {
    class: "spark",
    viewBox: `0 0 ${width} ${height}`,
    role: "img",
    "aria-label": label,
    preserveAspectRatio: "none",
  });
  if (known.length < 2) {
    const line = svg("line", { x1: 0, y1: height / 2, x2: width, y2: height / 2, stroke: "currentColor", "stroke-dasharray": "4 4", "stroke-width": 1 });
    root.appendChild(line);
    return root;
  }
  const min = Math.min(...known.map((p) => p[1]));
  const max = Math.max(...known.map((p) => p[1]));
  const span = max - min || 1;
  const step = width / Math.max(1, values.length - 1);
  const points = known.map(([i, v]) => `${(i * step).toFixed(1)},${(height - 4 - ((v - min) / span) * (height - 8)).toFixed(1)}`);
  root.appendChild(svg("polyline", { points: points.join(" "), fill: "none", stroke: "currentColor", "stroke-width": 2, "vector-effect": "non-scaling-stroke" }));
  return root;
}
