import { expect, test, type Page } from "@playwright/test";
import { openSection } from "./sections";
import type { Vec2 } from "../../src/geometry";

// UX1 in the demo: landing basemap switch and provider setup, expanded map, overlay upload, form, mouse and
// two-point calibration, lock, undo, and the satellite underlay.
async function state(page: Page) {
  return page.evaluate(async () => (await import("/src/state/store.tsx")).uiStore.getState().state);
}
async function idle(page: Page) { await expect.poll(async () => (await state(page)).busy).toBeNull(); }
async function point(page: Page, p: Vec2): Promise<Vec2> {
  return page.evaluate(([x, y]) => (window as unknown as { __rawibumiPlan: { toPage(x: number, y: number): Vec2 } }).__rawibumiPlan.toPage(x, y), p);
}
async function overlay(page: Page) {
  return page.evaluate(async () => {
    const { parseImagery } = await import("/src/imagery/config.ts");
    const s = (await import("/src/state/store.tsx")).uiStore.getState().state;
    return parseImagery(s.view?.bundle.imagery).overlay;
  });
}
async function pngFile(page: Page, width: number, height: number) {
  const base64 = await page.evaluate(([w, h]) => {
    const c = document.createElement("canvas"); c.width = w; c.height = h;
    const g = c.getContext("2d")!; g.fillStyle = "#3a7"; g.fillRect(0, 0, w, h); g.fillStyle = "#fff"; g.fillRect(w / 4, h / 4, w / 2, h / 2);
    return c.toDataURL("image/png").split(",")[1];
  }, [width, height]);
  return { name: "roof.png", mimeType: "image/png", buffer: Buffer.from(base64, "base64") };
}
const tile = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==", "base64");

test("landing: Satellite is disabled until a provider is set up; expand and zoom keep the typed point", async ({ page }) => {
  await page.route("https://tiles.example.test/**", (route) => route.fulfill({ status: 200, contentType: "image/png", body: tile }));
  await page.goto("/");
  const switcher = page.locator(".start__map .map-basemaps");
  await expect(switcher).toHaveAttribute("data-basemap", "streets");
  await expect(switcher.getByRole("button", { name: "Satellite", exact: true })).toBeDisabled();
  await expect(switcher.getByRole("button", { name: "Satellite", exact: true })).toHaveAttribute("title", "Satellite needs a custom imagery provider.");
  await switcher.getByRole("button", { name: "Set up imagery provider", exact: true }).click();
  const dialog = page.locator("[data-imagery-provider]");
  await dialog.getByLabel("Tile URL template").fill("https://tiles.example.test/{z}/{x}/{y}.png?key=abc");
  await expect(dialog.getByRole("alert")).toContainText("Put the key in the key field");
  await dialog.getByLabel("Tile URL template").fill("https://tiles.example.test/{z}/{x}/{y}.png?key={key}");
  await dialog.getByLabel("Key (this browser only)").fill("browser-only-secret");
  await dialog.getByLabel("Attribution").fill("© Example imagery");
  await expect(dialog.getByRole("button", { name: "Save provider", exact: true })).toBeDisabled();
  await dialog.getByLabel("I accept this provider's terms of use for this purpose").check();
  await dialog.getByRole("button", { name: "Save provider", exact: true }).click();
  await switcher.getByRole("button", { name: "Hybrid", exact: true }).click();
  await expect(switcher).toHaveAttribute("data-basemap", "hybrid");
  await switcher.getByRole("button", { name: "Satellite", exact: true }).click();
  await expect(switcher).toHaveAttribute("data-basemap", "satellite");
  await page.getByRole("button", { name: "Expand map", exact: true }).click();
  const expanded = page.getByRole("dialog", { name: "Pick the site" });
  await expect(expanded.locator(".map-canvas")).toBeVisible();
  await expect(expanded.locator("[data-picked-point]")).toContainText("-6.2");
  await expanded.getByRole("button", { name: "Use this point", exact: true }).click();
  await expect(expanded).toHaveCount(0);
  await page.getByRole("button", { name: "Zoom to point", exact: true }).click();
  expect(await page.evaluate(() => localStorage.getItem("rawibumi.imagery.provider"))).not.toContain("browser-only-secret");
});

test("project overlay: upload, form, drag and undo, two-point calibration locks it, the menu unlocks it", async ({ page }) => {
  await page.goto("/"); await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible(); await page.keyboard.press("Alt+1"); await idle(page); await openSection(page, "Background image");
  const section = page.locator("[data-imagery-overlay]");
  await expect(section).toHaveAttribute("data-imagery-overlay", "none");
  await section.locator('input[type="file"]').setInputFiles(await pngFile(page, 400, 300));
  await idle(page);
  await expect(section).toHaveAttribute("data-imagery-overlay", "unlocked");
  const placed = (await overlay(page))!;
  expect([placed.width, placed.height, placed.transform.sx]).toEqual([400, 300, 0.05]);
  await expect.poll(() => page.evaluate(() => (document.querySelector("canvas.plan__layer") as HTMLCanvasElement | null) !== null)).toBe(true);

  // Form: one committed value is one step.
  const steps = (await state(page)).past.length;
  const rotation = section.getByLabel("Rotation");
  await rotation.fill("12.5"); await rotation.press("Enter"); await idle(page);
  await expect.poll(async () => (await overlay(page))!.transform.rotationDeg).toBeCloseTo(12.5, 6);
  expect((await state(page)).past.length).toBe(steps + 1);
  await rotation.fill("0"); await rotation.press("Enter"); await idle(page);

  // Drag inside the unlocked image moves it, as one undo step.
  await page.keyboard.press("Alt+3"); await idle(page);
  const before = (await overlay(page))!.transform.offset;
  const from = await point(page, [3, -5]), to = await point(page, [6, -3]);
  await page.mouse.move(...from); await page.mouse.down(); await page.mouse.move(...to, { steps: 8 }); await page.mouse.up(); await idle(page);
  const moved = (await overlay(page))!.transform.offset;
  expect(moved[0] - before[0]).toBeCloseTo(3, 1); expect(moved[1] - before[1]).toBeCloseTo(2, 1);
  await page.keyboard.press("Control+z"); await idle(page);
  await expect.poll(async () => (await overlay(page))!.transform.offset[0]).toBeCloseTo(before[0], 6);

  // Two-point calibration: two points 8 m apart on the image become 16 m apart, and the overlay locks.
  await page.keyboard.press("Shift+F10");
  await page.getByRole("menu", { name: "Plan actions" }).locator('[data-menu-item="overlayCalibrate"]').click();
  await expect(page.locator("[data-overlay-calibrate]")).toBeVisible();
  await page.mouse.click(...await point(page, [1, -6])); await page.mouse.click(...await point(page, [9, -6]));
  const distance = page.getByLabel("True distance (m)");
  await distance.fill("16"); await distance.press("Enter"); await idle(page);
  const calibrated = (await overlay(page))!;
  expect(calibrated.locked).toBe(true);
  expect(calibrated.transform.sx / placed.transform.sx).toBeCloseTo(2, 2);
  await page.keyboard.press("Alt+1");
  await expect(section).toHaveAttribute("data-imagery-overlay", "locked");

  // Locked: a drag on the image does not move it.
  await page.keyboard.press("Alt+3"); await idle(page);
  const lockedOffset = calibrated.transform.offset;
  await page.mouse.move(...await point(page, [4, -6])); await page.mouse.down(); await page.mouse.move(...await point(page, [7, -4]), { steps: 6 }); await page.mouse.up(); await idle(page);
  expect((await overlay(page))!.transform.offset).toEqual(lockedOffset);
  await page.mouse.click(...await point(page, [44, 25]), { button: "right" });
  await page.getByRole("menu", { name: "Plan actions" }).locator('[data-menu-item="overlayUnlock"]').click(); await idle(page);
  await expect.poll(async () => (await overlay(page))!.locked).toBe(false);
});

test("satellite underlay needs the provider; with it, the plan shows its attribution and the project keeps no key", async ({ page }) => {
  await page.route("https://tiles.example.test/**", (route) => route.fulfill({ status: 200, contentType: "image/png", body: tile }));
  await page.goto("/");
  await page.evaluate(() => {
    localStorage.setItem("rawibumi.imagery.provider", JSON.stringify({ name: "Test imagery", tileUrlTemplate: "https://tiles.example.test/{z}/{x}/{y}.png?key={key}", attribution: "© Test imagery", termsAccepted: true }));
    localStorage.setItem("rawibumi.imagery.key.browser-key:custom-imagery", "browser-only-secret");
  });
  await page.reload();
  await page.locator(".start__row").first().click(); await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+1"); await idle(page); await openSection(page, "Background image");
  await page.locator("[data-imagery-satellite]").getByLabel("Satellite underlay (custom provider)").click(); await idle(page);
  await expect(page.locator("[data-imagery-satellite]")).toHaveAttribute("data-imagery-satellite", "on");
  await page.keyboard.press("Alt+3");
  await expect(page.locator(".plan__attrib")).toHaveText("© Test imagery");
  const saved = JSON.stringify((await state(page)).view!.bundle.imagery);
  expect(saved).toContain("browser-key:custom-imagery");
  expect(saved).not.toContain("browser-only-secret");
});
