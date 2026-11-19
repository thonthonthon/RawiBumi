import { expect, test, type Page } from "@playwright/test";

// USE1 in the demo: Suggest stringing lands as a draft and Apply restrings in one step; Remove and Change model are
// undoable; the notation explains its own syntax; the engine checks replace the "not wired" rows; the shading-free
// pitch is applied; test components can be hidden.

async function state(page: Page) {
  return page.evaluate(async () => (await import("/src/state/store.tsx")).uiStore.getState().state);
}
async function idle(page: Page) { await expect.poll(async () => (await state(page)).busy).toBeNull(); }
const design = async (page: Page) => (await state(page)).view!.bundle.electrical_design;
const panel = (page: Page) => page.locator(".taskpanel");
const notation = (page: Page) => panel(page).locator(".input--notation").first();

async function open(page: Page, step: string) {
  await page.addInitScript(() => window.localStorage.setItem("rawibumi.language", "en"));
  await page.goto("/");
  await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press(step);
  await idle(page);
}
async function undo(page: Page) {
  await page.locator(".stage").click({ position: { x: 5, y: 60 } });
  await page.keyboard.press("Control+z"); await idle(page);
}

test("Suggest stringing fills the notation as a draft with engine checks; Apply restrings in one undo step", async ({ page }) => {
  const errors: string[] = []; page.on("pageerror", (e) => errors.push(e.message));
  await open(page, "Alt+6");
  const before = (await design(page)).strings.map((s) => s.string_id).sort();
  await panel(page).getByRole("button", { name: "Suggest stringing" }).first().click();
  const result = panel(page).locator('[data-suggest-result="available"]').first();
  await expect(result).toContainText("Engine suggestion");
  const suggested = await notation(page).inputValue();
  expect(suggested).not.toBe("16,0 ; 16,0 ; 16,0 ; 14,14");
  // The draft is checked by the engine before Apply; no "not wired" rows remain.
  await expect(panel(page).locator("[data-engine-checks] [data-check=max_voltage]").first()).toBeVisible();
  await expect(panel(page)).not.toContainText("check endpoint not wired");
  await panel(page).getByRole("button", { name: "Apply layout" }).first().click(); await idle(page);
  const after = await design(page);
  expect(after.strings.every((s) => s.target_mppt_instance_id)).toBe(true);
  // The committed notation pads empty inputs (19,0); the string lengths per MPPT are the suggestion's.
  const lengths = (text: string) => text.split(";").map((m) => m.split(",").map((v) => v.trim()).filter((v) => v && v !== "0").join(","));
  expect(lengths(await notation(page).inputValue())).toEqual(lengths(suggested));
  await undo(page);
  expect((await design(page)).strings.map((s) => s.string_id).sort()).toEqual(before);
  expect(errors).toEqual([]);
});

test("Remove unassigns the inverter's strings and Change model swaps it; each is one undo step", async ({ page }) => {
  await open(page, "Alt+6");
  const inv = (await design(page)).inverter_instances[0];
  const lifecycle = panel(page).locator(`[data-inverter-lifecycle="${inv.inverter_instance_id}"]`);
  await expect(lifecycle).toContainText(inv.inverter_definition_revision_id);
  await expect(lifecycle.locator("[data-readiness]")).toHaveAttribute("data-readiness", "ready");

  await lifecycle.getByRole("button", { name: "Change model…" }).click();
  await lifecycle.getByRole("combobox", { name: "New inverter model" }).selectOption("inv-demo-100k");
  await lifecycle.getByRole("button", { name: "Change", exact: true }).click(); await idle(page);
  expect((await design(page)).inverter_instances[0].inverter_definition_revision_id).toBe("inv-demo-100k");
  await expect(panel(page).locator(`[data-inverter-lifecycle="${inv.inverter_instance_id}"] [data-readiness]`)).toHaveAttribute("data-readiness", "needs_values");
  await undo(page);
  expect((await design(page)).inverter_instances[0].inverter_definition_revision_id).toBe(inv.inverter_definition_revision_id);

  const strung = (await design(page)).strings.filter((s) => s.target_mppt_instance_id).length;
  await panel(page).locator(`[data-inverter-lifecycle="${inv.inverter_instance_id}"]`).getByRole("button", { name: "Remove" }).click();
  await expect(panel(page).getByRole("alert")).toContainText(`Its ${strung} strings stay, unassigned`);
  await panel(page).getByRole("alert").getByRole("button", { name: "Remove" }).click(); await idle(page);
  expect((await design(page)).inverter_instances).toHaveLength(0);
  expect((await design(page)).strings.every((s) => !s.target_mppt_instance_id)).toBe(true);
  await undo(page);
  expect((await design(page)).inverter_instances).toHaveLength(1);
});

test("the notation shows the right form for common mistakes", async ({ page }) => {
  await open(page, "Alt+6");
  await notation(page).fill("16x2/16");
  await expect(panel(page).locator(".issue--blocking").first()).toContainText('Write it as "16,16 ; 16"');
});

test("the shading-free pitch is computed and applied; test components can be hidden", async ({ page }) => {
  await open(page, "Alt+4");
  await panel(page).getByRole("radio", { name: "Shading-free" }).click();
  await expect(panel(page).locator("[data-shading-free-pitch]")).not.toHaveAttribute("data-shading-free-pitch", "");
  await expect(panel(page)).not.toContainText("the shading-free pitch mode");

  await page.keyboard.press("Alt+6"); await idle(page);
  const model = panel(page).getByRole("combobox").filter({ has: page.locator("option", { hasText: "MPPT" }) }).first();
  await expect(model.locator("option")).toHaveCount(2);
  await panel(page).getByRole("checkbox", { name: "Show test components" }).uncheck();
  await expect(model.locator("option")).toHaveCount(0);
});
