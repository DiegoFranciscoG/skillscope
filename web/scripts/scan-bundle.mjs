// Acceptance check "cero claves en el front": scan the published site for credentials.
// Usage: node scripts/scan-bundle.mjs ../site   (exit code 1 when something is found)
import { readdirSync, readFileSync, statSync } from "node:fs";
import { extname, join, relative } from "node:path";

const root = process.argv[2] ?? "../site";

// Real credential formats, checked in every published file (code and data).
const SECRET_PATTERNS = [
  ["GitHub token", /\b(gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b/],
  ["Google API key", /\bAIza[0-9A-Za-z_-]{35}\b/],
  ["AWS access key", /\b(AKIA|ASIA)[0-9A-Z]{16}\b/],
  ["Slack token", /\bxox[abprs]-[0-9A-Za-z-]{10,}\b/],
  ["Private key", /-----BEGIN [A-Z ]*PRIVATE KEY-----/],
  ["JSON Web Token", /\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}/],
  ["Generic secret assignment", /\b(api[_-]?key|secret|token|password)\s*[:=]\s*["'][A-Za-z0-9/+_-]{24,}["']/i],
];

// The application code must not even reference a credential mechanism: there is no backend.
const CODE_PATTERNS = [
  ["Authorization header", /Authorization/],
  ["Bearer scheme", /Bearer\s/],
  ["process.env", /process\.env/],
  ["Vite env variable", /import\.meta\.env\.VITE_/],
];

const files = [];
const walk = (dir) => {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) walk(path);
    else files.push(path);
  }
};
walk(root);

const findings = [];
for (const file of files) {
  const ext = extname(file);
  if (![".js", ".css", ".html", ".json", ".xml", ".svg", ".txt", ".map"].includes(ext)) continue;
  const text = readFileSync(file, "utf-8");
  const isCode = ext === ".js" || ext === ".css" || (ext === ".html" && !relative(root, file).startsWith("s"));
  const patterns = isCode ? [...SECRET_PATTERNS, ...CODE_PATTERNS] : SECRET_PATTERNS;
  for (const [label, pattern] of patterns) {
    if (pattern.test(text)) findings.push(`${relative(root, file)}: ${label}`);
  }
}

if (findings.length) {
  console.error(`Posibles credenciales en el sitio publicado:\n- ${findings.join("\n- ")}`);
  process.exit(1);
}
console.log(`OK: ${files.length} archivos revisados, sin credenciales.`);
