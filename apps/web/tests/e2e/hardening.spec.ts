import { expect, test, type Locator, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test.beforeEach(async ({ page }) => {
  await page.route("https://nominatim.openstreetmap.org/**", (r) => r.abort());
});
async function open(page: Page) {
  await page.goto("/"); await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible();
}
async function tabTo(page: Page, locator: Locator) {
  for (let i = 0; i < 100; i++) {
    if (await locator.evaluate((el) => el === document.activeElement)) return;
    await page.keyboard.press("Tab");
  }
  throw new Error(`Keyboard could not reach ${await locator.textContent()}`);
}
async function axe(page: Page) {
  expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze()).violations).toEqual([]);
}

test("keyboard entry, skip link and all nine steps work with reduced motion", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const errors: string[] = []; page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/"); await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to main content" })).toBeFocused();
  await page.keyboard.press("Enter"); await expect(page.locator("#main-content")).toBeFocused();
  await tabTo(page, page.locator(".start__row").first()); await page.keyboard.press("Enter");
  await expect(page.locator(".rail")).toBeVisible();
  for (const shortcut of ["1", "3", "4", "2", "6", "7", "9", "0", null]) {
    if (shortcut) await page.keyboard.press(`Alt+${shortcut}`);
    else await page.locator(".rail").getByRole("button", { name: /Report & export/ }).click();
    await expect(page.locator('#main-content')).toBeVisible();
    await expect(page.locator('.rail [aria-current="step"]')).toHaveCount(1);
  }
  await page.keyboard.press("Alt+6");
  await tabTo(page, page.getByRole("button", { name: "Select string S1", exact: true }));
  await page.keyboard.press("Enter"); await expect(page.locator(".taskpanel")).toContainText("16 modules selected");
  await page.keyboard.press("Alt+0");
  const monthly = page.getByRole("radio", { name: "Monthly", exact: true });
  await tabTo(page, monthly); await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("radio", { name: "Loss waterfall", exact: true })).toBeFocused();
  await expect(page.getByRole("radio", { name: "Loss waterfall", exact: true })).toHaveAttribute("aria-checked", "true");
  expect(errors).toEqual([]);
});

test("import is a keyboard modal, file picker is reachable, Escape restores focus", async ({ page }) => {
  await open(page); await page.keyboard.press("Alt+2");
  const opener = page.getByRole("button", { name: "Import PAN / template…" });
  await tabTo(page, opener); await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Import", exact: true });
  await expect(dialog).toBeVisible();
  await tabTo(page, dialog.getByLabel("Choose a file"));
  for (let i = 0; i < 20; i++) {
    await page.keyboard.press("Tab");
    expect(await dialog.evaluate((el) => el.contains(document.activeElement))).toBe(true);
  }
  await page.keyboard.press("Alt+0");
  await expect(page.locator('.rail [aria-current="step"]')).toContainText("Components");
  await axe(page);
  await page.screenshot({ path: test.info().outputPath("f8-after-components.png") });
  await page.keyboard.press("Escape"); await expect(dialog).toBeHidden(); await expect(opener).toBeFocused();
});

test("undo and redo work in 3D and results; modal and text editing preserve history", async ({ page }) => {
  await open(page); await page.keyboard.press("Alt+3");
  await page.keyboard.press("b");
  for (const text of ["50,0", "@12,8"]) { await page.keyboard.type(text); await page.keyboard.press("Enter"); }
  const undo = page.getByRole("button", { name: "Undo", exact: true }).first();
  await expect(undo).toBeEnabled();
  await page.getByRole("button", { name: "Isometric", exact: true }).click();
  await page.keyboard.press("Control+z"); await expect(page.getByRole("button", { name: "Redo", exact: true }).first()).toBeEnabled(); await expect(undo).toBeDisabled();
  await page.keyboard.press("Control+y"); await expect(undo).toBeEnabled();
  await page.keyboard.press("Alt+0"); await page.keyboard.press("Control+z"); await expect(page.getByRole("button", { name: "Redo", exact: true }).first()).toBeEnabled(); await expect(undo).toBeDisabled();
  await page.keyboard.press("Control+Shift+z"); await expect(undo).toBeEnabled();
  await page.keyboard.press("Alt+2");
  await page.getByRole("button", { name: "Import PAN / template…" }).click();
  await page.keyboard.press("Control+z"); await expect(undo).toBeEnabled();
  await page.keyboard.press("Escape");
  await page.keyboard.press("Alt+1");
  const address = page.locator("[data-site-address]");
  await address.focus(); await page.keyboard.type("Keyboard edit"); await page.keyboard.press("Control+z");
  await expect(address).not.toHaveValue(/Keyboard edit/); await expect(undo).toBeEnabled();
});

test("a new empty project has actionable states without invented results", async ({ page }) => {
  await page.goto("/"); await page.getByRole("button", { name: "Create project", exact: true }).click();
  await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+6"); await axe(page);
  await page.getByRole("button", { name: "SLD", exact: true }).click();
  await expect(page.locator(".sld")).toContainText(/inverter/i); await axe(page);
  await page.keyboard.press("Alt+0"); await expect(page.getByRole("heading", { name: "No results yet" })).toBeVisible(); await axe(page);
  await page.locator(".rail").getByRole("button", { name: /Report & export/ }).click(); await expect(page.getByText("Run a simulation first: the report is built from a run's results.")).toBeVisible(); await axe(page);
});

test("delete confirmation starts on Cancel, contains focus and preserves the project on Escape", async ({ page }) => {
  await open(page); await page.keyboard.press("Alt+3");
  // Setup selects an existing engine entity; the confirmation itself is exercised by keys.
  await page.evaluate(async () => {
    const { uiStore } = await import("/src/state/store.tsx");
    const id = uiStore.getState().state.entities[0].id;
    uiStore.getState().dispatch({ type: "select", ids: [id] });
    window.dispatchEvent(new CustomEvent("rawibumi:delete-request", { detail: id }));
  });
  const dialog = page.getByRole("alertdialog");
  await expect(dialog.getByRole("button", { name: "Cancel", exact: true })).toBeFocused();
  await axe(page); await page.keyboard.press("Escape"); await expect(dialog).toBeHidden();
  await expect(page.locator(".inspectorpane")).toContainText("Roof A");
});

test("more than 200 strings keep tree and table DOM bounded with keyboard access to the last row", async ({ page }) => {
  await open(page); await page.keyboard.press("Alt+6");
  const count = await page.evaluate(async () => {
    const { engine } = await import("/src/client.ts");
    const { engineCommand } = await import("/src/state/history.ts");
    const view = await engineCommand("Scale setup", () => engine.addSurface("demo-project", { name: "C&I test roof", origin_x_m: 100, origin_y_m: 0, width_m: 50, height_m: 30, base_elevation_m: 0, surface_type: "flat_roof", usable_for_pv: true }));
    const field = await engineCommand("Scale setup", () => engine.createPvField("demo-project", { name: "Long table", support_surface_id: view!.bundle.scene.surfaces.at(-1)!.surface_id, module_definition_revision_id: "mod-demo-550", orientation: "portrait", azimuth_deg: 0, tilt_deg: 0, module_gap_x_m: 0.02, module_gap_y_m: 0.02, row_pitch_m: 2.4, mounting_height_m: 0.2, perimeter_setback_m: 1, obstacle_setback_m: 0.5 }));
    const result = await engineCommand("Scale setup", () => engine.createStrings("demo-project", { string_length: 1, pv_field_id: field!.bundle.scene.pv_fields.at(-1)!.pv_field_id, allow_shorter_remainder: false }));
    return result!.bundle.electrical_design.strings.length;
  });
  expect(count).toBeGreaterThan(200);
  const tree = page.getByRole("treegrid", { name: /Electrical topology/ });
  await expect.poll(() => tree.getByRole("row").count()).toBeLessThan(80);
  await tree.focus(); await page.keyboard.press("End");
  await expect(tree).toContainText(`S${count}`);
  expect(await page.locator(".stringtable tbody tr").count()).toBeLessThan(80);
  await axe(page);
});

test("unavailable WebGL preserves coordinate entry, project creation and explanatory plan/3D fallbacks", async ({ page }) => {
  const errors: string[] = []; page.on("pageerror", (e) => errors.push(e.message));
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (...args: Parameters<typeof original>) {
      if (String(args[0]).startsWith("webgl")) return null;
      return original.apply(this, args);
    } as typeof original;
  });
  await page.goto("/");
  await expect(page.getByText("Map unavailable.")).toBeVisible();
  await page.getByRole("button", { name: "Create project", exact: true }).click();
  await expect(page.locator(".plan__nogl")).toContainText("WebGL 2");
  await page.getByRole("button", { name: "Isometric", exact: true }).click();
  await expect(page.locator(".plan__nogl")).toContainText("WebGL 2");
  expect(errors).toEqual([]);
});
