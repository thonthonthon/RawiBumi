import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

async function openLayout(page: Page) {
  await page.goto("/"); await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible(); await page.keyboard.press("Alt+4");
  return page.locator(".taskpanel");
}

test("legacy re-fill previews counts and strings; cancel is read-only and confirm edits in place", async ({ page }) => {
  const errors: string[] = []; page.on("pageerror", (e) => errors.push(e.message));
  const p = await openLayout(page);
  await p.locator(".card-row", { hasText: "Roof A array" }).getByRole("button", { name: "Re-fill", exact: true }).click();
  await expect(p.getByLabel("Support surface")).toBeEnabled();
  await expect(p.getByRole("combobox", { name: "Module", exact: true })).toBeEnabled();
  // USE3b (approved 2026-11-12): with nothing changed, Re-fill re-packs the field on its current roof.
  await expect(p.getByRole("button", { name: "Apply re-fill" })).toBeEnabled();
  await p.getByLabel("Tilt").fill("15");
  await p.getByRole("button", { name: "Apply re-fill" }).click();
  const dialog = page.getByRole("alertdialog", { name: "Preview re-fill", exact: true });
  await expect(dialog).toContainText("Modules: 76 →"); await expect(dialog).toContainText("STC power:");
  await expect(dialog).toContainText("S1, S2, S3, S4, S5");
  await expect(dialog.getByRole("button", { name: "Cancel", exact: true })).toBeFocused();
  await page.screenshot({ path: "../../.ai/validation/S7a_refill_dialog.png" });
  expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze()).violations).toEqual([]);
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(p.locator(".card-row", { hasText: "Roof A array" })).toContainText("tilt 10°");
  await p.locator(".card-row", { hasText: "Roof A array" }).getByRole("button", { name: "Re-fill", exact: true }).click();
  await p.getByLabel("Tilt").fill("15");
  await p.getByRole("button", { name: "Apply re-fill" }).click();
  await dialog.getByRole("button", { name: "Confirm re-fill", exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(p.locator(".card-row", { hasText: "Roof A array" })).toContainText("tilt 15°");
  await expect(p.locator(".card-row")).toHaveCount(1);
  await expect(p.getByRole("button", { name: "Apply fill", exact: true })).toBeEnabled();
  const counts = await page.evaluate(async () => {
    const { engine } = await import("/src/client.ts"); const v = await engine.project("demo-project");
    return [v.bundle.scene.pv_fields.length, v.bundle.electrical_design.strings.length];
  });
  expect(counts).toEqual([1, 0]); expect(errors).toEqual([]);
});

test("occupied surfaces offer re-fill and invalid azimuth never sends a command", async ({ page }) => {
  const p = await openLayout(page);
  await expect(p.getByRole("button", { name: "Apply fill", exact: true })).toBeEnabled();
  await expect(p).toContainText("Roof A already has 'Roof A array'. Apply fill replaces its layout");
  await p.locator(".card-row", { hasText: "Roof A array" }).getByRole("button", { name: "Re-fill", exact: true }).click();
  await p.getByLabel("Azimuth").fill("360");
  await expect(p.getByRole("alert")).toContainText("Azimuth must be in [0, 360).");
  await expect(p.getByRole("button", { name: "Apply re-fill" })).toBeDisabled();
});

test("stale warning is above Run and opens the existing legacy field", async ({ page }) => {
  await openLayout(page);
  await page.evaluate(async () => {
    const { engine } = await import("/src/client.ts");
    const original = engine.executionReadiness;
    engine.executionReadiness = async (...args) => ({ ...await original(...args), findings: [
      { rule_id: "MODULES_NOT_SIMULATED", severity: "warning", category: "execution", message: "5 placed modules (2.75 kWp STC) will not be simulated." },
      { rule_id: "SCENE_PV_FIELD_LAYOUT_STALE", entity_id: "fld-a", severity: "warning", category: "scene", message: "Packing inputs changed." }
    ] });
  });
  await page.keyboard.press("Alt+9");
  const p = page.locator(".taskpanel");
  await expect(p).toContainText("5 placed modules (2.75 kWp STC)");
  const warning = p.locator("li", { hasText: "Re-fill available" });
  await expect(warning).toContainText("Packing inputs changed.");
  const wy = (await warning.boundingBox())!.y;
  expect(wy).toBeLessThan((await p.getByRole("button", { name: "Validate and run" }).boundingBox())!.y);
  await warning.getByRole("button", { name: "Re-fill", exact: true }).click();
  await expect(p).toContainText("Re-fill Roof A array");
  await expect(p.getByLabel("Support surface")).toBeEnabled();
});

test("legacy field deletion previews impact and updates the plan only after confirmation", async ({ page }) => {
  const p = await openLayout(page);
  await p.getByRole("button", { name: "Delete field", exact: true }).click();
  const dialog = page.getByRole("alertdialog", { name: "Preview field deletion" });
  await expect(dialog).toContainText("Modules: 76 → 0");
  await expect(dialog).toContainText("S1, S2, S3, S4, S5");
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(p.locator(".card-row")).toHaveCount(1);
  await p.getByRole("button", { name: "Delete field", exact: true }).click();
  await dialog.getByRole("button", { name: "Confirm delete field" }).click();
  await expect(p.locator(".card-row")).toHaveCount(0);
  const remaining = await page.evaluate(async () => {
    const { engine } = await import("/src/client.ts"); const v = await engine.project("demo-project");
    return v.bundle.scene.module_instances.length;
  });
  expect(remaining).toBe(0);
});


test("a structured commit refusal lists its module and field without changing the layout", async ({ page }) => {
  const p = await openLayout(page);
  await page.evaluate(async () => {
    const { engine } = await import("/src/client.ts"); const { ApiError } = await import("/src/types.ts");
    engine.updatePvField = async () => { throw new ApiError("Server refused changed geometry", 422, {
      message: "Server refused changed geometry", conflicts: [{ module_instance_id: "module-conflict", pv_field_id: "fld-a", other_id: "obstacle-conflict" }]
    }); };
  });
  await p.locator(".card-row").getByRole("button", { name: "Re-fill", exact: true }).click();
  await p.getByLabel("Tilt").fill("15"); await p.getByRole("button", { name: "Apply re-fill" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Confirm re-fill", exact: true }).click();
  await expect(page.getByRole("alertdialog")).toBeHidden();
  await expect(page.locator(".toasts")).toContainText("Server refused changed geometry");
  await expect(p.getByRole("alert")).toContainText("module-conflict · fld-a · obstacle-conflict");
  await expect(p.locator(".card-row")).toContainText("tilt 10°");
});
