// Shapes of the JSON files written by indexer/index.py (docs/modelo-datos.md §4).

export type RepoType =
  | "skill"
  | "plugin"
  | "marketplace"
  | "mcp_server"
  | "agent"
  | "command"
  | "hook"
  | "awesome_list"
  | "template";

export interface Components {
  quality: number;
  maintenance: number;
  adoption: number;
  social: number;
  utility: number;
  risk: number;
}

export interface Item {
  id: string;
  owner: string;
  name: string;
  type: RepoType;
  category: string;
  categories: string[];
  cause: string;
  score: number;
  components: Components;
  risk: { level: 0 | 1 | 2 | 3; penalty: number; flags: string[] };
  stars: number;
  forks: number;
  pushed_at: string | null;
  license: string | null;
  summary: string;
  keywords: string[];
  install: string | null;
  counts: Record<string, number>;
  first_seen: string;
  mentions_30d: number;
  trend: number;
  /** Stars gained in the last 7 days (GitHub star history), when measured recently. */
  stars_7d?: number | null;
  /** More than half of the stars arrived this week. */
  star_spike?: boolean;
  co: string[];
  sample: boolean;
}

export interface SourceStatus {
  id: string;
  status?: "ok" | "partial" | "failed" | "skipped";
  reason?: string;
  calls?: number;
}

export interface NeededRow {
  category: string;
  demand: number;
  supply: number;
  ratio: number;
}

export interface IndexData {
  schema_version: number;
  build_id: string;
  built_at: string;
  site_url: string;
  totals: {
    repos: number;
    catalog: number;
    /** Repositories found and waiting for analysis. */
    queue?: number;
    artifacts: Record<string, number>;
    by_type: Record<string, number>;
    by_category: Record<string, number>;
    by_risk: Record<string, number>;
  };
  sources: SourceStatus[];
  labels: { types: Record<string, string>; categories: Record<string, string> };
  files: Record<string, string>;
  lists: {
    newest?: string[];
    most_used: string[];
    most_mentioned: string[];
    trending: string[];
    most_useful: string[];
    safest: string[];
    riskiest: string[];
    most_needed: NeededRow[];
  };
  gaps: number;
  items: Item[];
}

export interface InstallStep {
  label: string;
  command: string;
}

export interface Evidence {
  path: string;
  line: number;
  snippet: string;
}

export interface RiskFlag {
  id: string;
  severity: "high" | "medium" | "low";
  penalty: number;
  title: string;
  why: string;
  evidence: Evidence[];
}

export interface Factor {
  id: string;
  label: string;
  value: string;
  points: number;
  max: number;
}

export interface Component {
  id: string;
  label: string;
  points: number;
  max: number;
  factors: Factor[];
}

export interface Detail {
  id: string;
  what: string;
  when: string[];
  install: { kind: string; steps: InstallStep[]; note: string; one_liner: string | null };
  risks: RiskFlag[];
  score: { total: number; components: Component[] };
  artifacts: { kind: string; path: string; name: string; valid: boolean; issues: string[] }[];
  tools: string[];
  readme_lang: string;
  collections: string[];
  co: string[];
  topics: string[];
  category_terms: string[];
  answers: string[];
  signals: { stars: (number | null)[]; mentions: Record<string, number> };
  links: { repo: string | null; license: string | null };
  archived: boolean;
  created_at: string | null;
}

export interface DemandQuestion {
  key: string;
  source: string;
  title: string;
  url: string;
  author: string;
  author_url: string | null;
  created_at: string;
  answered: boolean;
  tags: string[];
  topic: string | null;
}

export interface DemandTopic {
  id: string;
  label: string;
  keywords: string[];
  subjects?: string[];
  category: string;
  demand: number;
  questions: number;
  supply?: string[];
  examples: string[];
}

export interface DemandData {
  build_id: string;
  attribution: string;
  /** True in the offline demo: the questions are fictional and link to example.com. */
  sample?: boolean;
  items: DemandQuestion[];
  topics: DemandTopic[];
  gaps: (DemandTopic & { topic: string })[];
  categories: { category: string; label: string; demand: number }[];
}

/** A repository found by discovery and not analyzed yet (data/candidates.json). */
export interface Candidate {
  id: string;
  d: string; // description, untrusted text
  t: string[]; // topics
  l: string; // language
  s: number; // stars
  p: string | null; // last push
}
