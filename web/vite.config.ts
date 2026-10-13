import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";

const SITE = resolve(fileURLToPath(new URL(".", import.meta.url)), "../site");

// GitHub Pages cannot send HTTP headers (docs/investigacion.md E1, S6), so the policy travels in
// a <meta> tag. frame-ancestors/report-uri are not allowed there (#28); nginx in docker compose
// sends the full header set. Trusted Types make any innerHTML regression throw at runtime.
export const CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self'",
  "img-src 'self' data:",
  "font-src 'self'",
  "connect-src 'self' https://api.github.com", // live GitHub search, only on click
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "manifest-src 'self'",
  "worker-src 'self'",
  "require-trusted-types-for 'script'",
  "trusted-types 'none'",
].join("; ");

function securityHeaders(): Plugin {
  return {
    name: "skillscope-csp",
    apply: "build",
    transformIndexHtml: {
      order: "post",
      handler(html, ctx) {
        // Subresource Integrity for every emitted script and stylesheet.
        const integrity = (file: string): string | null => {
          const chunk = ctx.bundle?.[file];
          if (!chunk) return null;
          const source = chunk.type === "chunk" ? chunk.code : chunk.source;
          return `sha384-${createHash("sha384").update(source).digest("base64")}`;
        };
        const withSri = html.replace(
          /<(script|link)([^>]*?)(src|href)="\.\/([^"]+)"([^>]*)>/g,
          (tag, name: string, before: string, attr: string, file: string, after: string) => {
            const value = /\.(js|css)$/.test(file) ? integrity(file) : null;
            if (!value || tag.includes("integrity=")) return tag;
            const cross = tag.includes("crossorigin") ? "" : ' crossorigin="anonymous"';
            return `<${name}${before}${attr}="./${file}"${after} integrity="${value}"${cross}>`;
          },
        );
        return {
          html: withSri,
          tags: [{ tag: "meta", attrs: { "http-equiv": "Content-Security-Policy", content: CSP }, injectTo: "head-prepend" }],
        };
      },
    },
  };
}

const TYPES: Record<string, string> = {
  ".json": "application/json",
  ".bin": "application/octet-stream",
  ".xml": "application/xml",
  ".svg": "image/svg+xml",
  ".html": "text/html; charset=utf-8",
};

/** Dev server: serve the pipeline output (site/) so `npm run dev` shows real data. */
function siteData(): Plugin {
  return {
    name: "skillscope-site-data",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const path = decodeURIComponent((req.url ?? "").split("?")[0] ?? "");
        if (!/^\/(data|s|badge)\/|^\/feed\.(xml|json)$/.test(path)) return next();
        const file = normalize(join(SITE, path));
        if (!file.startsWith(SITE) || !existsSync(file)) return next();
        res.setHeader("Content-Type", TYPES[extname(file)] ?? "application/octet-stream");
        res.end(readFileSync(file));
      });
    },
  };
}

export default defineConfig({
  base: "./",
  plugins: [siteData(), securityHeaders()],
  build: {
    outDir: SITE,
    emptyOutDir: false,
    target: "es2022",
    assetsInlineLimit: 0,
    modulePreload: { polyfill: false },
    reportCompressedSize: false,
  },
  preview: { port: 4173, strictPort: true },
  test: {
    environment: "happy-dom",
    include: ["test/**/*.test.ts"],
    coverage: {
      provider: "v8",
      include: ["src/**/*.ts"],
      exclude: ["src/main.ts", "src/search/lexicon.generated.ts", "src/types.ts"],
      thresholds: { lines: 70, functions: 70, branches: 60, statements: 70 },
    },
  },
});
