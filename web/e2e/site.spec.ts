import { expect, type Page, test } from "@playwright/test";

/** Run the 5-minute update check now (hook exposed by main.ts). */
async function triggerCheck(page: Page): Promise<void> {
  await page.evaluate(() =>
    (window as unknown as { __skillscope: { check: () => Promise<unknown> } }).__skillscope.check(),
  );
}

/** Collect CSP violations and console errors for the whole page lifetime. */
async function watch(page: Page): Promise<{ errors: string[] }> {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  await page.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (event) => {
      console.error(`CSP violation: ${event.violatedDirective} ${event.blockedURI}`);
    });
  });
  return { errors };
}

test.describe("Skillscope", () => {
  test("loads the index, shows the real build time and a clean console", async ({ page }) => {
    const { errors } = await watch(page);
    await page.goto("./");
    await expect(page.locator("#status")).toContainText("Actualizado");
    await expect(page.locator(".row-main").first()).toBeVisible();
    await expect(page.locator("meta[http-equiv='Content-Security-Policy']")).toHaveCount(1);
    expect(await page.locator("script[type=module]").getAttribute("integrity")).toMatch(/^sha384-/);
    expect(errors).toEqual([]);
  });

  test("search by need returns the three blocks", async ({ page }) => {
    await page.goto("./");
    await page.locator("#q").fill("necesito revisar pull requests");
    const exact = page.locator(".block").filter({ hasText: "Resuelve exactamente eso" });
    await expect(exact).toContainText("pr-review-kit");
    await expect(page).toHaveURL(/q=necesito/);
    await page.locator("#q").fill("migrar trabajos cobol del mainframe");
    await expect(page.locator(".empty")).toContainText("Nadie ha publicado una skill para esto");
  });

  test("keyboard: / focuses search, j/k move, Enter opens, Escape closes", async ({ page, isMobile }) => {
    test.skip(isMobile, "physical keyboard shortcuts are a desktop feature");
    await page.goto("./");
    await expect(page.locator(".row-main").first()).toBeVisible();
    await page.keyboard.press("/");
    await expect(page.locator("#q")).toBeFocused();
    await page.keyboard.press("Escape");
    await page.keyboard.press("j");
    await page.keyboard.press("j");
    const second = page.locator(".row-main").nth(1);
    await expect(second).toBeFocused();
    await page.keyboard.press("k");
    await expect(page.locator(".row-main").first()).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.locator("#drawer")).toBeVisible();
    await expect(page.locator("#drawer")).toContainText("Qué riesgos tiene");
    await expect(page.locator("#drawer-title")).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(page.locator("#drawer")).toBeHidden();
    await expect(page.locator(".row-main").first()).toBeFocused();
  });

  test("detail answers the four questions and copies the install command", async ({ page, context, browserName, isMobile }) => {
    test.skip(browserName !== "chromium", "clipboard permissions are chromium-only");
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await page.goto("./?r=nimbus-labs%2Fpr-review-kit");
    const drawer = page.locator("#drawer");
    for (const heading of ["Qué hace", "Cuándo usarla", "Cómo se instala", "Qué riesgos tiene"]) {
      await expect(drawer.getByRole("heading", { name: heading })).toBeVisible();
    }
    await drawer.getByRole("button", { name: /Copiar: Agregar el marketplace/ }).click();
    await expect(drawer.getByRole("button", { name: /Copiar: Agregar/ })).toHaveText("Copiado");
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
      "/plugin marketplace add nimbus-labs/pr-review-kit",
    );
    if (isMobile) {
      const box = await drawer.boundingBox();
      expect(box?.width).toBeGreaterThan(300); // full-screen sheet on phones
    }
  });

  test("a new build replaces the content in place, keeping scroll and search text", async ({ page }) => {
    await page.setViewportSize({ width: 1000, height: 420 });
    await page.goto("./?q=review");
    await expect(page.locator(".block").first()).toBeVisible();
    await page.evaluate(() => ((window as unknown as { marker: number }).marker = 42));
    await page.locator("#q").fill("revisar codigo y seguridad");
    await expect(page.locator(".block").first()).toBeVisible();
    await page.mouse.wheel(0, 260);
    await page.waitForTimeout(200);
    const before = await page.evaluate(() => window.scrollY);
    expect(before).toBeGreaterThan(100);

    const response = await page.request.get("./data/index.json");
    const data = await response.json();
    const clone = { ...data.items[0], id: "brand-new/skill", owner: "brand-new", name: "skill", first_seen: new Date().toISOString() };
    data.build_id = `${data.build_id}-next`;
    data.items = [...data.items, clone];
    await page.route("**/data/index.json", (route) => route.fulfill({ json: data, headers: { etag: '"next"' } }));
    await triggerCheck(page);

    await expect(page.locator("#live")).toContainText("Índice actualizado: 1 repositorios nuevos");
    expect(await page.evaluate(() => (window as unknown as { marker?: number }).marker)).toBe(42); // no reload
    await expect(page.locator("#q")).toHaveValue("revisar codigo y seguridad");
    const after = await page.evaluate(() => window.scrollY);
    expect(Math.abs(after - before)).toBeLessThanOrEqual(4);

    await page.locator("#q").fill("");
    await page.getByRole("tab", { name: "Explorar" }).click();
    await page.locator("#f-sort").selectOption("new").catch(() => undefined);
  });

  test("keeps the data and says so when the network fails", async ({ page }) => {
    await page.goto("./");
    await expect(page.locator(".row-main").first()).toBeVisible();
    const count = await page.locator(".row-main").count();
    await page.route("**/data/index.json", (route) => route.abort("internetdisconnected"));
    await triggerCheck(page);
    await expect(page.locator("#status")).toContainText("Sin conexión");
    await expect(page.locator(".row-main")).toHaveCount(count);
  });

  test("gaps view shows unmet demand with attribution", async ({ page }) => {
    await page.goto("./?tab=gaps");
    await expect(page.locator(".gaps")).toContainText("Huecos del ecosistema");
    await expect(page.locator(".card").first()).toContainText(/cobol|vba/i);
    await expect(page.locator(".attribution").last()).toContainText("CC BY-SA");
  });

  test("filters live in a bottom sheet on phones", async ({ page, isMobile }) => {
    test.skip(!isMobile, "mobile only");
    await page.goto("./");
    await page.getByRole("button", { name: "Filtros" }).click();
    await expect(page.locator("#filters-sheet")).toBeVisible();
    await page.locator("#f-risk").selectOption("3");
    await page.getByRole("button", { name: "Listo" }).click();
    await expect(page.locator("#count")).toContainText("repositorios");
    await expect(page).toHaveURL(/risk=3/);
  });
});
