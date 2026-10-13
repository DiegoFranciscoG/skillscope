// @vitest-environment node
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

const script = join(process.cwd(), "scripts", "scan-bundle.mjs");
const dirs: string[] = [];

function site(files: Record<string, string>): string {
  const root = mkdtempSync(join(tmpdir(), "skillscope-scan-"));
  dirs.push(root);
  for (const [name, content] of Object.entries(files)) {
    mkdirSync(join(root, name, ".."), { recursive: true });
    writeFileSync(join(root, name), content);
  }
  return root;
}

const scan = (root: string) => spawnSync(process.execPath, [script, root], { encoding: "utf-8" });

afterEach(() => {
  for (const dir of dirs.splice(0)) rmSync(dir, { recursive: true, force: true });
});

describe("published bundle scan", () => {
  it("passes a clean site", () => {
    const result = scan(site({ "index.html": "<p>ok</p>", "assets/app.js": "console.log(1)" }));
    expect(result.status).toBe(0);
  });

  it("fails when a token is planted in the data", () => {
    const token = ["ghp", "_", "A".repeat(36)].join("");
    const result = scan(site({ "data/index.json": JSON.stringify({ note: token }) }));
    expect(result.status).toBe(1);
    expect(result.stderr).toContain("GitHub token");
  });

  it("fails when application code reads environment credentials", () => {
    const result = scan(site({ "assets/app.js": "fetch(u, { headers: { Authorization: k } })" }));
    expect(result.status).toBe(1);
  });
});
