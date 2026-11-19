import { expect, test, type Page } from "@playwright/test";

// F6 done-when (plan C2): every SLD node selects its plan object and back; the
// output matches the IEC symbol sheet. Against the demo engine.

const hook = <T,>(page: Page, fn: string, ...args: number[]) =>
  page.evaluate(([f, a]) => {
    const h = (window as unknown as { __rawibumiPlan: Record<string, (...x: number[]) => unknown> }).__rawibumiPlan;
    return h[f as string](...(a as number[])) as T;
  }, [fn, args] as const);

const node = (page: Page, id: string) => page.locator(`[data-node="${id}"]`);
const row = (page: Page, s: string) => page.locator(".stringtable tbody tr", { hasText: s });

async function openSld(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+6");
  await expect(page.locator('.rail [aria-current="step"]')).toContainText("Electrical");
  await page.getByRole("button", { name: "SLD", exact: true }).click();
  await expect(node(page, "inv:inv-01")).toBeVisible();
  return errors;
}

test("every SLD node selects its modules on the plan, and the plan selection comes back to the SLD", async ({ page }) => {
  const errors = await openSld(page);
  // SLD → plan: a string, an MPPT and the inverter each select exactly their modules.
  await node(page, "str:S1").click();
  await expect(node(page, "str:S1")).toHaveAttribute("data-selected", "full");
  await expect(row(page, "S1")).toHaveAttribute("aria-selected", "true");
  await expect(row(page, "S2")).toHaveAttribute("aria-selected", "false");
  await expect(node(page, "inv:inv-01")).toHaveAttribute("data-selected", "partial");

  await node(page, "mppt:mppt-4").click();
  await expect(row(page, "S4")).toHaveAttribute("aria-selected", "true");
  await expect(row(page, "S5")).toHaveAttribute("aria-selected", "true");
  await expect(row(page, "S1")).toHaveAttribute("aria-selected", "false");
  await expect(node(page, "str:S4")).toHaveAttribute("data-selected", "full");

  await node(page, "inv:inv-01").click();
  for (const s of ["S1", "S2", "S3", "S4", "S5"]) await expect(row(page, s)).toHaveAttribute("aria-selected", "true");

  // Busbar, grid and load have no plan object: not focusable, not selectable.
  await expect(node(page, "bus")).toHaveAttribute("aria-hidden", "true");

  // Plan → SLD: click one module of S3 on the plan; the SLD marks S3 partly selected.
  await page.getByRole("button", { name: "Top", exact: true }).click();
  await page.waitForTimeout(300);
  const n = await hook<number>(page, "moduleCount");
  let s3 = -1;
  for (let i = 0; i < n && s3 < 0; i++) if ((await hook<string | null>(page, "moduleString", i)) === "S3") s3 = i;
  const c = await hook<[number, number]>(page, "moduleCentre", s3);
  const [x, y] = await hook<[number, number]>(page, "toPage", c[0], c[1]);
  await page.keyboard.press("v");
  await page.mouse.click(x, y);
  await page.getByRole("button", { name: "SLD", exact: true }).click();
  await expect(node(page, "str:S3")).toHaveAttribute("data-selected", "partial");
  await expect(node(page, "str:S1")).toHaveAttribute("data-selected", "none");
  // A whole string selected from the table shows as fully selected.
  await row(page, "S3").click();
  await expect(node(page, "str:S3")).toHaveAttribute("data-selected", "full");
  await expect(node(page, "mppt:mppt-3")).toHaveAttribute("data-selected", "full");

  // Double-click opens the plan with the selection kept.
  await node(page, "str:S2").dblclick();
  await expect(page.getByRole("button", { name: "Top", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(row(page, "S2")).toHaveAttribute("aria-selected", "true");
  expect(errors).toEqual([]);
});

test("nodes are reachable by keyboard: Tab, Enter selects, Escape clears", async ({ page }) => {
  const errors = await openSld(page);
  await node(page, "str:S1").focus();
  await page.keyboard.press("Enter");
  await expect(node(page, "str:S1")).toHaveAttribute("data-selected", "full");
  await page.keyboard.press("Tab");
  await page.keyboard.press("Enter");
  await expect(page.locator('[data-node][data-selected="full"]').first()).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator('[data-node][data-selected="full"]')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("the SLD draws every symbol exactly as the symbol sheet does", async ({ page }) => {
  const errors = await openSld(page);
  const used = await page.locator("[data-node] [data-symbol-body]").evaluateAll((els) => els.map((e) => [e.getAttribute("data-symbol-body"), e.innerHTML] as [string, string]));
  expect(new Set(used.map(([id]) => id))).toEqual(new Set(["pv-string", "mppt-input", "inverter", "busbar", "grid", "load"]));
  await page.getByRole("button", { name: "Symbol sheet" }).click();
  await expect(page.locator("[data-sheet-symbol]")).toHaveCount(14);
  for (const [id, html] of used) {
    const sheet = await page.locator(`[data-sheet-symbol="${id}"] [data-symbol-body="${id}"]`).innerHTML();
    if (id === "busbar") {
      // The busbar is the one stretchable symbol: same elements and classes, longer along y.
      const strip = (h: string) => h.replace(/y[12]="[^"]*"/g, "");
      expect(strip(html)).toBe(strip(sheet));
    } else expect(html, id).toBe(sheet);
  }
  expect(errors).toEqual([]);
});

test("the SLD regenerates after an engine edit: a split string appears on its MPPT", async ({ page }) => {
  const errors = await openSld(page);
  await expect(node(page, "str:S6")).toHaveCount(0);
  await page.getByRole("button", { name: "Top", exact: true }).click();
  await page.waitForTimeout(300);
  const n = await hook<number>(page, "moduleCount");
  const s1: number[] = [];
  for (let i = 0; i < n; i++) if ((await hook<string | null>(page, "moduleString", i)) === "S1") s1.push(i);
  const c = await hook<[number, number]>(page, "moduleCentre", s1[7]);
  const [x, y] = await hook<[number, number]>(page, "toPage", c[0], c[1]);
  await page.keyboard.press("x");
  await page.mouse.click(x, y);
  await expect(page.locator(".taskpanel").getByLabel("MPPT layout")).toHaveValue("8,8 ; 16,0 ; 16,0 ; 14,14");
  await page.getByRole("button", { name: "SLD", exact: true }).click();
  await expect(node(page, "str:S6")).toBeVisible();
  const wire = page.locator('[data-wire="w:str:S6"]');
  await expect(wire).toHaveCount(1);
  expect(errors).toEqual([]);
});
