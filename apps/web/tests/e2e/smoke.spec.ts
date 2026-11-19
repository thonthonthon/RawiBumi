import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

// Accessibility is a ratchet: violations recorded in quality/axe-baseline.json
// may only go down, per page. Any new rule violation fails. Update the
// baseline with UPDATE_AXE_BASELINE=1 after a deliberate fix.
const BASELINE = path.join(process.cwd(), "quality/axe-baseline.json");
const STEPS = [["site", "1"], ["scene", "3"], ["layout", "4"], ["components", "2"], ["electrical", "6"], ["meteo", "7"], ["simulate", "9"], ["results", "0"], ["export", null]];
const found: Record<string, Record<string, number>> = {};

async function openDemoProject(page: Page) {
  await page.goto("/");
  await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible();
}

async function axe(page: Page, id: string) {
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  found[id] = Object.fromEntries(result.violations.map((v) => [v.id, v.nodes.length]));
}

test.describe.configure({ mode: "serial" });

test("demo start screen and workspace load without page errors", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await openDemoProject(page);
  await page.waitForLoadState("networkidle");
  expect(errors).toEqual([]);
});

test("design tokens and drawing font are loaded", async ({ page }) => {
  await page.goto("/");
  const selection = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--rb-role-selection").trim());
  // Chromium resolves the alias, so the role reads as the final colour.
  expect(selection.toUpperCase()).toBe("#FFB238");
  const osifont = await page.evaluate(async () => {
    await document.fonts.load("12px osifont");
    return document.fonts.check("12px osifont");
  });
  expect(osifont).toBe(true);
});

test("command palette, step shortcuts and language switch", async ({ page }) => {
  await openDemoProject(page);
  await page.keyboard.press("Control+k");
  const input = page.getByPlaceholder("Type a command or a step");
  await expect(input).toBeVisible();
  await input.fill("pv layout");
  await page.keyboard.press("Enter");
  await expect(page.locator('.rail [aria-current="step"]')).toContainText("PV layout");

  await page.keyboard.press("Alt+6");
  await expect(page.locator('.rail [aria-current="step"]')).toContainText("Electrical");

  await page.keyboard.press("Control+k");
  await page.getByPlaceholder("Type a command or a step").fill("Bahasa");
  await page.keyboard.press("Enter");
  await expect(page.locator(".rail")).toContainText("Tata letak PV");
  await page.keyboard.press("Control+k");
  await page.getByPlaceholder("Ketik perintah atau langkah").fill("English");
  await page.keyboard.press("Enter");
  await expect(page.locator(".rail")).toContainText("PV layout");
});

test("shortcut sheet opens with Shift+? and closes with Escape", async ({ page }) => {
  await openDemoProject(page);
  await page.keyboard.press("Shift+?");
  await expect(page.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeHidden();
});

test("accessibility: start screen and every step", async ({ page }) => {
  // Ten axe scans in one test: 29 s at F7.1 against the 30 s default, 54 s on a slower run at F7.2.
  test.setTimeout(120_000);
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await axe(page, "start");
  await openDemoProject(page);
  for (const [step, shortcut] of STEPS) {
    if (shortcut) await page.keyboard.press(`Alt+${shortcut}`);
    else await page.locator(".rail").getByRole("button", { name: /Report & export/ }).click();
    await page.waitForTimeout(150);
    await axe(page, `step-${step}`);
  }
  if (process.env.UPDATE_AXE_BASELINE === "1") {
    fs.mkdirSync(path.dirname(BASELINE), { recursive: true });
    fs.writeFileSync(BASELINE, JSON.stringify({ note: "axe violations (nodes) per page; may only go down", pages: found }, null, 2) + "\n");
    return;
  }
  const baseline: Record<string, Record<string, number>> = fs.existsSync(BASELINE) ? JSON.parse(fs.readFileSync(BASELINE, "utf8")).pages ?? {} : {};
  const worse: string[] = [];
  for (const [pageId, rules] of Object.entries(found))
    for (const [rule, n] of Object.entries(rules)) if (n > (baseline[pageId]?.[rule] ?? 0)) worse.push(`${pageId}: ${rule} ${n} (baseline ${baseline[pageId]?.[rule] ?? 0})`);
  expect(worse, "New or increased axe violations").toEqual([]);
});
