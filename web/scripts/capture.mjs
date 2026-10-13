// README screenshots and GIF frames from the sample site (fictional data, labelled as such).
// Usage: npm run preview (other terminal), then: node scripts/capture.mjs
// Writes docs/img/*.png and docs/img/frames/*.png; scripts/make_gif.py turns the frames into a GIF.
import { mkdirSync } from "node:fs";
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
} finally {
  // Some installed Edge builds never finish a graceful close; do not wait forever.
  await Promise.race([browser.close(), new Promise((resolve) => setTimeout(resolve, 5_000))]);
}
console.log("screenshots written to docs/img/");
process.exit(0);
