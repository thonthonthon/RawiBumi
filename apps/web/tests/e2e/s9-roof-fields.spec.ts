import { expect, test } from "@playwright/test";

async function state(page: import("@playwright/test").Page) {
  return page.evaluate(async () => (await import("/src/state/store.tsx")).uiStore.getState().state);
}

test("hosted-roof Resize previews, Cancel preserves everything, Confirm re-fills and cascade Delete removes the field", async ({ page }) => {
  await page.goto("/"); await page.locator(".start__row").first().click(); await expect(page.locator(".rail")).toBeVisible(); await page.keyboard.press("Alt+3");
  await page.locator(".taskpanel .layer__name", { hasText: "Roof A" }).click(); const before = (await state(page)).view!;
  const inspector = page.locator(".inspectorpane"); await inspector.getByRole("spinbutton", { name: "Resize %", exact: true }).fill("80");
  await inspector.getByRole("button").filter({ hasText: /^Resize$/ }).click();
  const dialog = page.getByRole("alertdialog", { name: "Roof carries PV fields" });
  await expect(dialog).toContainText("Roof A array"); await expect(dialog).toContainText("Modules: 76 →"); await expect(dialog).toContainText("STC power:"); await expect(dialog).toContainText("S1");
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click(); await expect(dialog).toBeHidden(); expect((await state(page)).view).toEqual(before);
  await inspector.getByRole("button").filter({ hasText: /^Resize$/ }).click(); await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Confirm roof change" }).click(); await expect(dialog).toBeHidden();
  await expect.poll(async () => (await state(page)).view!.bundle.scene.module_instances.length).not.toBe(76);
  const after = (await state(page)).view!; expect(after.bundle.scene.pv_fields).toHaveLength(1); expect(after.bundle.electrical_design.strings).toEqual([]);
  const roof = after.scene_view.local_features.find((f) => f.id === "srf-roof-a")!; expect(Math.max(...roof.polygon.map((p) => p[0])) - Math.min(...roof.polygon.map((p) => p[0]))).toBeCloseTo(42*.8,9);
  await expect(inspector).not.toContainText("engine + local edits");
  await page.keyboard.press("Delete"); const first = page.getByRole("alertdialog");
  await expect(first).toContainText("Deletes Roof A from the engine. Undo is available while this edit remains in session history."); await expect(first).not.toContainText("unavailable");
  await first.getByRole("button", { name: "Delete roof and its 1 PV fields" }).click(); await expect(dialog).toBeVisible(); await expect(dialog).toContainText(`Modules: ${after.bundle.scene.module_instances.length} → 0`);
  await dialog.getByRole("button", { name: "Confirm roof change" }).click(); await expect(dialog).toBeHidden();
  await expect.poll(async () => (await state(page)).view!.bundle.scene.surfaces.length).toBe(0);
  const deleted = (await state(page)).view!; expect(deleted.bundle.scene.pv_fields).toEqual([]); expect(deleted.bundle.scene.module_instances).toEqual([]); expect(deleted.bundle.electrical_design.strings).toEqual([]);
});
