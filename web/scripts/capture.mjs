// README screenshots and GIF frames from the sample site (fictional data, labelled as such).
// Usage: npm run preview (other terminal), then: node scripts/capture.mjs
// Writes docs/img/*.png, docs/img/insignia-ejemplo.svg, docs/img/social-preview.png (1280x640, for
// Settings > General > Social preview) and docs/img/frames/*.png; scripts/make_gif.py builds the GIF.
import { copyFileSync, mkdirSync, readFileSync } from "node:fs";
import { chromium, devices } from "@playwright/test";

const base = process.argv[2] ?? "http://localhost:4173/";
const out = new URL("../../docs/img/", import.meta.url);
const frames = new URL("frames/", out);
mkdirSync(frames, { recursive: true });
const path = (dir, name) => new URL(name, dir).pathname.replace(/^\/([A-Za-z]:)/, "$1");

const browser = await chromium.launch({ channel: process.env.PW_CHANNEL || "chromium" });
try {
  const desktop = await browser.newPage({
    viewport: { width: 1280, height: 800 },
    colorScheme: "light",
    locale: "es-EC",
    timezoneId: "America/Guayaquil",
  });
  let frame = 0;
  const shot = async (page, name) => {
    await page.waitForTimeout(250);
    await page.screenshot({ path: path(frames, `${String(frame++).padStart(2, "0")}-${name}.png`) });
  };

  await desktop.goto(base);
  await desktop.locator(".row-main").first().waitFor();
  await shot(desktop, "explore");
  await desktop.screenshot({ path: path(out, "explorar.png") });

  await desktop.locator("#q").click();
  for (const part of ["revisar", "revisar pull", "revisar pull requests"]) {
    await desktop.locator("#q").fill(part);
    await shot(desktop, "typing");
  }
  await desktop.locator(".row-main").first().waitFor();
  await shot(desktop, "search");

  await desktop.locator(".row-main").first().click();
  await desktop.locator("#drawer-title").waitFor();
  await shot(desktop, "detail");
  await desktop.screenshot({ path: path(out, "busqueda-ficha.png") });

  await desktop.keyboard.press("Escape");
  await desktop.goto(`${base}?tab=gaps`);
  await desktop.locator(".gaps .card").first().waitFor();
  await shot(desktop, "gaps");
  await desktop.screenshot({ path: path(out, "huecos.png") });

  const phone = await browser.newPage({ ...devices["Pixel 7"], colorScheme: "dark", locale: "es-EC" });
  await phone.goto(`${base}?q=${encodeURIComponent("revisar pull requests")}`);
  await phone.locator(".row-main").first().waitFor();
  await phone.waitForTimeout(250);
  await phone.screenshot({ path: path(out, "movil.png") });

  // Risk evidence of the riskiest fictional repository, scrolled to its risk section.
  const wide = await browser.newPage({
    viewport: { width: 1280, height: 900 },
    colorScheme: "light",
    locale: "es-EC",
    timezoneId: "America/Guayaquil",
  });
  await wide.goto(`${base}?r=${encodeURIComponent("demo_shadowtools/super-agent-pack")}`);
  await wide.locator("#drawer-title").waitFor();
  await wide.waitForTimeout(250);
  await wide
    .locator("#drawer h3", { hasText: "Qué riesgos tiene" })
    .evaluate((heading) => heading.scrollIntoView({ block: "start" }));
  await wide.waitForTimeout(250);
  const panel = await wide.locator("#drawer").boundingBox();
  if (!panel) throw new Error("drawer not visible");
  const top = Math.max(0, panel.y);
  await wide.screenshot({
    path: path(out, "riesgos.png"),
    clip: { x: panel.x, y: top, width: panel.width, height: Math.min(900 - top, panel.height) },
  });

  // Static page that search engines index (schema.org SoftwareSourceCode).
  await wide.goto(`${base}s/demo_nimbus-labs/pr-review-kit/`);
  await wide.waitForTimeout(250);
  await wide.screenshot({ path: path(out, "pagina-estatica.png") });

  copyFileSync(
    path(new URL("../../site/badge/demo_nimbus-labs/", import.meta.url), "pr-review-kit.svg"),
    path(out, "insignia-ejemplo.svg"),
  );

  // Social preview card built from the explore screenshot.
  const card = await browser.newPage({ viewport: { width: 1280, height: 640 } });
  const screenshot = readFileSync(path(out, "explorar.png")).toString("base64");
  await card.setContent(`<!doctype html><html lang="es"><head><meta charset="utf-8"><style>
    * { box-sizing: border-box; margin: 0; }
    body { width: 1280px; height: 640px; overflow: hidden; display: grid;
      grid-template-columns: 560px 1fr; background: #111318; color: #f4f5f7;
      font-family: "Segoe UI", system-ui, -apple-system, sans-serif; }
    .text { padding: 72px 0 64px 72px; display: flex; flex-direction: column; gap: 22px; }
    .brand { font-size: 64px; font-weight: 700; letter-spacing: -1px; }
    .brand span { color: #6d8dff; }
    .lead { font-size: 27px; line-height: 1.35; color: #d5d8de; }
    ul { list-style: none; padding: 0; display: grid; gap: 10px; font-size: 21px; color: #b8bdc7; }
    li::before { content: "▸ "; color: #6d8dff; }
    .foot { margin-top: auto; font-size: 18px; color: #8a909c; }
    .shot { position: relative; }
    .shot img { position: absolute; top: 70px; left: 40px; width: 900px; border-radius: 14px;
      box-shadow: 0 30px 80px rgba(0,0,0,.55); border: 1px solid #2a2e37; }
  </style></head><body>
    <div class="text">
      <div class="brand">Skill<span>scope</span></div>
      <p class="lead">Encuentra, entiende y evalúa skills y plugins para agentes de código publicados en GitHub.</p>
      <ul><li>Puntaje 0–100 auditable</li><li>Riesgos con evidencia</li><li>Comando de instalación exacto</li><li>Huecos del ecosistema</li></ul>
      <p class="foot">Sitio estático · USD 0 · se actualiza cada ~30 min</p>
    </div>
    <div class="shot"><img alt="" src="data:image/png;base64,${screenshot}"></div>
  </body></html>`);
  await card.waitForTimeout(250);
  await card.screenshot({ path: path(out, "social-preview.png") });
} finally {
  // Some installed Edge builds never finish a graceful close; do not wait forever.
  await Promise.race([browser.close(), new Promise((resolve) => setTimeout(resolve, 5_000))]);
}
console.log("screenshots written to docs/img/");
process.exit(0);
