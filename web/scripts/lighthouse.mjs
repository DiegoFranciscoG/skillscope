// Acceptance check: Lighthouse >= 95 in performance and accessibility, on mobile and desktop.
// Usage: npm run lighthouse [url]   (default http://localhost:4173/, served by `npm run preview`)
// PW_CHANNEL=chrome|msedge reuses an installed browser instead of Playwright's Chromium.
// Scores vary between runs on the same machine, so each form factor reports the median of
// LH_RUNS runs (default 3), as Lighthouse's own variability guide recommends.
import { mkdirSync, writeFileSync } from "node:fs";
import { chromium } from "@playwright/test";
import lighthouse, { desktopConfig } from "lighthouse";

const url = process.argv[2] ?? "http://localhost:4173/";
const minimum = Number(process.env.LH_MIN ?? "0.95");
const required = ["performance", "accessibility"];
const categories = [...required, "best-practices", "seo"];
const runs = Math.max(1, Number(process.env.LH_RUNS ?? "3"));
const port = 9333;
const median = (values) => [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)];
const outDir = new URL("../lighthouse-report/", import.meta.url);

const browser = await chromium.launch({
  channel: process.env.PW_CHANNEL || "chromium",
  args: [`--remote-debugging-port=${port}`],
});

const rows = [];
let failed = false;
try {
  for (const formFactor of ["mobile", "desktop"]) {
    const config = formFactor === "desktop" ? desktopConfig : undefined;
    const samples = [];
    for (let run = 0; run < runs; run++) {
      const result = await lighthouse(
        url,
        { port, logLevel: process.env.LH_LOG ?? "error", output: "html", onlyCategories: categories },
        config,
      );
      if (!result) throw new Error("Lighthouse returned no result");
      if (run === 0) {
        mkdirSync(outDir, { recursive: true });
        writeFileSync(new URL(`${formFactor}.html`, outDir), result.report);
      }
      samples.push(result.lhr.categories);
    }
    const scores = Object.fromEntries(
      categories.map((id) => [id, median(samples.map((sample) => sample[id]?.score ?? 0))]),
    );
    rows.push({ formFactor, ...scores });
    for (const id of required) if (scores[id] < minimum) failed = true;
  }
} finally {
  // Lighthouse keeps its own CDP connection open, which can stall a graceful close.
  await Promise.race([browser.close(), new Promise((resolve) => setTimeout(resolve, 5_000))]);
}

mkdirSync(outDir, { recursive: true });
writeFileSync(new URL("summary.json", outDir), JSON.stringify(rows, null, 2) + "\n");
const percent = (row) =>
  Object.fromEntries(Object.entries(row).map(([k, v]) => [k, typeof v === "number" ? Math.round(v * 100) : v]));
console.table(rows.map(percent));
if (failed) {
  console.error(`Lighthouse: performance and accessibility must be >= ${Math.round(minimum * 100)}`);
  process.exit(1);
}
console.log(`Lighthouse OK (>= ${Math.round(minimum * 100)} in ${required.join(" and ")})`);
process.exit(0);
