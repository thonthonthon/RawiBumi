import { expect, test, type Page } from "@playwright/test";
import { openSection } from "./sections";

// S14b in the demo: the orientation tolerance and a per-MPPT override with a reason, pairing chips, and the
// replicate button's table rule. Each is a design command and one undo step.

async function state(page: Page) {
  return page.evaluate(async () => (await import("/src/state/store.tsx")).uiStore.getState().state);
}
async function idle(page: Page) { await expect.poll(async () => (await state(page)).busy).toBeNull(); }
const design = async (page: Page) => (await state(page)).view!.bundle.electrical_design;
const panel = (page: Page) => page.locator(".taskpanel");

async function openElectrical(page: Page) {
  await page.goto("/");
  await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+6");
  await expect(page.locator('.rail [aria-current="step"]')).toContainText("Electrical");
  await idle(page);
}
async function undo(page: Page) {
  await page.locator(".stage").click({ position: { x: 5, y: 60 } });
  await page.keyboard.press("Control+z"); await idle(page);
}

test("the tolerance and an MPPT override are design commands, shown in the checks and undone in one step each", async ({ page }) => {
  const errors: string[] = []; page.on("pageerror", (e) => errors.push(e.message));
  await openElectrical(page);
  await expect(panel(page).locator(".notwired")).toHaveCount(0);
  await openSection(page, "Rules");
  const tolerance = panel(page).locator("[data-orientation-tolerance] input");
  await expect(tolerance).toHaveValue("1");
  await tolerance.fill("0.5"); await tolerance.press("Enter"); await idle(page);
  expect((await design(page)).orientation_policy?.normal_angle_tolerance_deg).toBe(0.5);
  expect((await state(page)).view!.topology_checks!.basis).toContain("orientation tolerance 0.5° between module normals");
  // Out of range is refused in the browser and sends nothing.
  await tolerance.fill("2"); await tolerance.press("Enter");
  await expect(page.locator(".toasts")).toContainText("between 0° and 1°");
  expect((await design(page)).orientation_policy?.normal_angle_tolerance_deg).toBe(0.5);

  const inv = (await design(page)).inverter_instances[0];
  await panel(page).getByRole("checkbox", { name: "Override orientation rule for MPPT 1" }).first().check();
  const reason = panel(page).getByLabel("Override reason for MPPT 1").first();
  await reason.fill("Same roof plane, within survey tolerance"); await reason.press("Enter"); await idle(page);
  expect((await design(page)).orientation_policy?.overrides).toEqual([{ mppt_instance_id: inv.mppt_instance_ids[0], reason: "Same roof plane, within survey tolerance" }]);

  await undo(page);
  expect((await design(page)).orientation_policy?.overrides ?? []).toEqual([]);
  await undo(page);
  expect((await design(page)).orientation_policy?.normal_angle_tolerance_deg ?? 1).toBe(1);
  expect(errors).toEqual([]);
});

test("pairing chips save the pairing; strings outside it get the pairing warning", async ({ page }) => {
  await openElectrical(page);
  const inv = (await design(page)).inverter_instances[0];
  const fields = (await state(page)).view!.bundle.scene.pv_fields;
  expect(fields.length).toBeGreaterThan(0);
  const chips = panel(page).locator(".chips").first().locator("button.chip");
  await expect(chips.first()).toHaveAttribute("aria-pressed", "false");
  await expect(panel(page)).toContainText("No fields paired: notation Apply draws from every field.");
  await chips.first().click(); await idle(page);
  expect((await design(page)).inverter_instances[0].paired_pv_field_ids).toEqual([fields[0].pv_field_id]);
  await expect(chips.first()).toHaveAttribute("aria-pressed", "true");
  const checks = (await state(page)).view!.topology_checks!.strings.flatMap((s) => s.checks.filter((c) => c.code === "pairing"));
  expect(checks.length).toBeGreaterThan(0);
  await chips.first().click(); await idle(page);
  expect((await design(page)).inverter_instances[0].paired_pv_field_ids).toBeUndefined();
  expect(inv.inverter_instance_id).toBeTruthy();
});

test("replicate is disabled with its reason when the selection has no table (the seed demo has none)", async ({ page }) => {
  await openElectrical(page);
  const modules = (await state(page)).modules;
  expect(modules.some((m) => /\/\d+\.\d+$/.test(m.id))).toBe(false);
  await page.evaluate(async (ids) => (await import("/src/state/store.tsx")).uiStore.getState().dispatch({ type: "select", ids }), modules.slice(0, 2).map((m) => m.id));
  const replicate = panel(page).getByRole("button", { name: "Replicate pattern", exact: true });
  await expect(replicate).toBeDisabled();
  await expect(panel(page)).toContainText("Select a module of an explicit table to replicate its wiring.");
});
