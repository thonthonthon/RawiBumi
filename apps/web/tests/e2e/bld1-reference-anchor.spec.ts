import { expect, test } from "@playwright/test";

test("saved centre anchor follows typed position and orientation, then moves to origin", async ({ page }) => {
  await page.goto("/");
  await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+3");
  await expect(page.locator(".toollist")).toBeVisible();
  // A separate roof keeps this test independent of the sample's PV fields.
  const id = await page.evaluate(async () => {
    const { mockApi, setDemoLatency } = await import("/src/demo/mockApi.ts");
    const { uiStore } = await import("/src/state/store.tsx");
    setDemoLatency(0);
    const view = await mockApi.sceneCommand("p", { command_type: "draw_polygon", target_entity_ids: [], parameters: { name: "BLD1 roof", surface_type: "flat_roof", vertices: [[50, 0], [60, 0], [60, 6], [50, 6]] } });
    const id = view.bundle.scene.surfaces.at(-1)!.surface_id;
    uiStore.getState().dispatch({ type: "setView", view });
    uiStore.getState().dispatch({ type: "select", ids: [id] });
    return id;
  });
  const inspector = page.locator(".inspectorpane");
  await inspector.getByRole("button", { name: "Middle centre", exact: true }).click();
  async function geometry() {
    return page.evaluate(async id => {
      const { uiStore } = await import("/src/state/store.tsx");
      const { ownBox } = await import("/src/canvas/plan/edit.ts");
      const state = uiStore.getState().state;
      const surface = state.view!.bundle.scene.surfaces.find(s => s.surface_id === id)!;
      const polygon = state.entities.find(e => e.id === id)!.polygon;
      return { ...ownBox(polygon, surface.reference_anchor), polygon, anchor: surface.reference_anchor };
    }, id);
  }
  await expect.poll(async () => (await geometry()).anchor).toEqual({ u: "center", v: "center" });
  for (const [label, value] of [["Position X", "30"], ["Position Y", "20"], ["Orientation", "45"]]) {
    await inspector.getByLabel(label).fill(value);
    await inspector.getByLabel(label).press("Enter");
    await expect.poll(async () => {
      const box = await geometry();
      return label === "Position X" ? box.point[0] : label === "Position Y" ? box.point[1] : box.bearing;
    }).toBeCloseTo(Number(value), 6);
  }
  await expect.poll(async () => (await geometry()).bearing).toBeCloseTo(45, 6);
  let box = await geometry();
  expect(box.point[0]).toBeCloseTo(30, 6); expect(box.point[1]).toBeCloseTo(20, 6);
  expect(box.polygon[0][0]).toBeCloseTo(30 - Math.SQRT2, 6);
  expect(box.polygon[0][1]).toBeCloseTo(20 - 4 * Math.SQRT2, 6);
  await inspector.getByRole("button", { name: "Move reference point to origin", exact: true }).click();
  await expect.poll(async () => (await geometry()).point[0]).toBeCloseTo(0, 6);
  box = await geometry(); expect(box.point[1]).toBeCloseTo(0, 6);
  expect(box.bearing).toBeCloseTo(45, 6); expect(box.anchor).toEqual({ u: "center", v: "center" });
});
