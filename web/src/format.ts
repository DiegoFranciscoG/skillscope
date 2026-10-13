// Spanish formatting helpers for numbers, dates and labels.

const numberFormat = new Intl.NumberFormat("es", { notation: "compact", maximumFractionDigits: 1 });
const timeFormat = new Intl.DateTimeFormat("es", { hour: "2-digit", minute: "2-digit" });
const dateFormat = new Intl.DateTimeFormat("es", { day: "numeric", month: "short", year: "numeric" });

export function compact(value: number): string {
  return numberFormat.format(value);
}

export function clockTime(iso: string): string {
  return timeFormat.format(new Date(iso));
}

export function longDate(iso: string): string {
  return dateFormat.format(new Date(iso));
}

/** "hace 3 min", "hace 2 h", "hace 4 días" (minutes are floored, never "hace -1"). */
export function ago(iso: string, now: number = Date.now()): string {
  const seconds = Math.max(0, (now - Date.parse(iso)) / 1000);
  if (seconds < 60) return "hace menos de 1 min";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `hace ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `hace ${hours} h`;
  const days = Math.floor(hours / 24);
  return days === 1 ? "hace 1 día" : `hace ${days} días`;
}

export const RISK_LABELS = ["sin banderas", "riesgo bajo", "riesgo medio", "riesgo alto"] as const;
export const SEVERITY_LABELS: Record<string, string> = {
  high: "alta",
  medium: "media",
  low: "baja",
};
export const CAUSE_LABELS: Record<string, string> = {
  automate: "Automatizar tareas repetitivas",
  standardize: "Estandarizar un estilo",
  comply: "Cumplir una norma",
  onboard: "Acelerar la incorporación",
  integrate: "Integrar una herramienta externa",
  reduce_errors: "Reducir errores",
  generate_docs: "Generar documentos",
};
export const SOURCE_LABELS: Record<string, string> = {
  github: "GitHub",
  hackernews: "Hacker News",
  stackexchange: "Stack Exchange",
  reddit: "Reddit",
  devto: "DEV",
  mastodon: "Mastodon",
  lemmy: "Lemmy",
  bluesky: "Bluesky",
  youtube: "YouTube",
  npm: "npm",
};

const NEW_WINDOW_MS = 60 * 60 * 1000;

/** "nuevo" during one hour after the repository first entered the index. */
export function isNew(firstSeen: string, now: number = Date.now()): boolean {
  const seen = Date.parse(firstSeen);
  return Number.isFinite(seen) && now - seen >= 0 && now - seen < NEW_WINDOW_MS;
}
