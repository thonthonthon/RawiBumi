import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { rotateClockwise, setEdgeLength } from "../../src/canvas/plan/edit";
import type { ProjectView, ObstacleConflictDetail } from "../../src/types";
import type { Vec2 } from "../../src/geometry";

const API = process.env.RAWIBUMI_API;
if (!API || !/^http:\/\/127\.0\.0\.1:\d+$/.test(API) || API.endsWith(":8000"))
  throw new Error("S7b live tests require the isolated test launcher on RAWIBUMI_API (checked free port, not 8000).");
const path = (id: string) => `${API}/api/projects/${id}`;
async function view(request: APIRequestContext, id: string): Promise<ProjectView> {
  const result = await request.get(path(id)); expect(result.ok()).toBe(true); return result.json();
}
async function create(request: APIRequestContext, suffix: string, withRoof = true) {
  const name = `S7b ${suffix} ${Date.now()}`;
  const result = await request.post(`${API}/api/projects`, { data: { name, latitude_deg: -6.2, longitude_deg: 106.8, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" } });
  expect(result.ok()).toBe(true); const id: string = (await result.json()).bundle.project.project_id;
  if (withRoof) expect((await request.post(path(id) + "/surfaces/rectangle", { data: { name: "S7b roof", origin_x_m: 0, origin_y_m: 0, width_m: 20, height_m: 10, base_elevation_m: 0 } })).ok()).toBe(true);
  return { id, name };
}
async function open(page: Page, name: string, step = 3) { // MENU1: Scene is Alt+3
  await page.goto("/"); await page.locator(".start__row", { hasText: name }).click();
  await expect(page.locator(".rail")).toBeVisible(); await page.keyboard.press(`Alt+${step}`);
}
async function type(page: Page, value: string) {
  await page.keyboard.type(value); await expect(page.locator(".plan__typed")).toBeVisible(); await page.keyboard.press("Enter");
}
async function field(page: Page, request: APIRequestContext, id: string) {
  await page.keyboard.press("Alt+4");
  const button = page.locator(".taskpanel").getByRole("button", { name: "Apply fill", exact: true });
  await expect(button).toBeEnabled(); await button.click();
  await expect.poll(async () => (await view(request, id)).bundle.scene.pv_fields.length).toBe(1);
}
async function select(page: Page, name: string) {
  await page.locator(".taskpanel .layer__name", { hasText: name }).click();
}
// This fixture starts centred on its only roof, (10,5), and never pans or zooms.
// Read the rendered scale instead of exposing demo-only hooks in the live app.
async function point(page: Page, x: number, y: number): Promise<[number, number]> {
  return page.evaluate(([x, y]) => {
    const canvas = document.querySelector<HTMLCanvasElement>(".plan__canvas")!;
    const box = canvas.getBoundingClientRect();
    const bar = document.querySelector<HTMLElement>(".plan__scalebar")!;
    const metres = parseFloat(bar.parentElement!.querySelector("span")!.textContent!);
    const scale = parseFloat(bar.style.width) / metres;
    return [box.left + canvas.clientWidth / 2 + (x - 10) * scale, box.top + canvas.clientHeight / 2 - (y - 5) * scale];
  }, [x, y]);
}
async function uiRing(page: Page, id: string): Promise<Vec2[]> {
  return page.evaluate(async (id) => (await import("/src/state/store.tsx")).uiStore.getState().state.entities.find((e) => e.id === id)!.polygon, id);
}
async function sameUI(page: Page, id: string, expected: Vec2[]) {
  // The store can be saved before the browser has parsed and applied its response.
  await expect.poll(() => uiRing(page, id)).toEqual(expected);
  same(await uiRing(page, id), expected);
}
const ring = (v: ProjectView, id: string): Vec2[] => v.scene_view.local_features.find((f) => f.id === id)!.polygon.map(([x, y]) => [x, y]);
function same(actual: Vec2[], expected: Vec2[]) {
  expect(actual).toHaveLength(expected.length);
  for (let i = 0; i < expected.length; i++) for (let axis = 0; axis < 2; axis++) expect(Math.abs(actual[i][axis] - expected[i][axis])).toBeLessThanOrEqual(1e-9);
}

test("strung field: box refusal previews exact removals, confirmation deletes whole strings, move persists", async ({ page, request }) => {
  const { id, name } = await create(request, "obstacle removal"); await open(page, name); await field(page, request, id);
  const strings = await request.post(path(id) + "/strings", { data: { string_length: 6, allow_shorter_remainder: true } });
  expect(strings.ok()).toBe(true);
  const before = await view(request, id); expect(before.bundle.electrical_design.strings.some((s) => s.module_instance_ids.length === 6)).toBe(true);
  await open(page, name);
  const module = before.scene_view.local_features.find((f) => f.category === "module")!;
  const x = Math.min(...module.polygon.map((p) => p[0])) + 0.1, y = Math.min(...module.polygon.map((p) => p[1])) + 0.1;
  const refusal = page.waitForResponse((r) => r.url().endsWith("/obstacles/box") && r.request().method() === "POST");
  await page.keyboard.press("o"); await type(page, `${x},${y}`); await type(page, "@0.5,0.5");
  const refused = await refusal; expect(refused.status()).toBe(422); const detail: ObstacleConflictDetail = (await refused.json()).detail;
  const dialog = page.getByRole("alertdialog", { name: "Obstacle on modules", exact: true }); await expect(dialog).toBeVisible();
  const impact = detail.options.remove_modules; expect(impact.module_count).toBeGreaterThan(0); expect(impact.string_ids.length).toBeGreaterThan(0);
  for (const id of impact.string_ids) await expect(dialog).toContainText(id);
  await expect(dialog).toContainText(`${(impact.stc_power_w / 1000).toFixed(2)} kWp`);
  expect(await view(request, id)).toEqual(before);
  const commit = page.waitForResponse((r) => r.url().endsWith("/obstacles/box") && r.request().method() === "POST");
  await dialog.getByRole("button", { name: "Remove modules under obstacle", exact: true }).click();
  const committed = await commit; expect(committed.ok()).toBe(true); await expect(dialog).toBeHidden();
  const initialBody = refused.request().postDataJSON(), finalBody = committed.request().postDataJSON();
  expect(finalBody).toEqual({ ...initialBody, on_module_conflict: "remove_modules", discard_dependent_strings: true });
  let after = await view(request, id);
  expect(before.bundle.scene.module_instances.filter((m) => !after.bundle.scene.module_instances.some((n) => n.module_instance_id === m.module_instance_id)).map((m) => m.module_instance_id).sort()).toEqual(impact.module_instance_ids);
  expect(after.bundle.electrical_design.strings).toEqual(before.bundle.electrical_design.strings.filter((s) => !impact.string_ids.includes(s.string_id)));
  const obstacle = after.bundle.scene.obstacles.at(-1)!;
  await select(page, obstacle.name); await page.keyboard.press("m"); await type(page, `${x},${y}`); await type(page, "@30,0");
  await expect.poll(async () => ring(await view(request, id), obstacle.obstacle_id)[0][0]).toBeCloseTo(x + 30, 9);
  after = await view(request, id); await sameUI(page, obstacle.obstacle_id, ring(after, obstacle.obstacle_id));
});

test("free roof rotation, vertex and dimension match the preview; support elevation raises modules by 1.5 m", async ({ page, request }) => {
  const { id, name } = await create(request, "geometry parity"); await open(page, name); await select(page, "S7b roof");
  const before = await view(request, id), surface = before.bundle.scene.surfaces[0].surface_id;
  const expected = rotateClockwise(ring(before, surface), [10, 5], 30);
  await page.keyboard.press("r"); await type(page, "10,5");
  await page.keyboard.type("30"); await expect(page.locator(".plan__typed")).toContainText("30"); await page.keyboard.press("Enter");
  await expect.poll(async () => ring(await view(request, id), surface)).toEqual(expected);
  await sameUI(page, surface, expected);
  await page.keyboard.press("v");
  const a = await point(page, ...expected[0]), target = await point(page, expected[0][0] - 1, expected[0][1]);
  const vertexResponse = page.waitForResponse((r) => r.url().endsWith("/scene/commands") && r.request().postDataJSON().command.command_type === "move_vertex");
  await page.mouse.move(...a); await page.mouse.down(); await page.keyboard.down("Alt"); await page.mouse.move(...target, { steps: 6 }); await page.mouse.up(); await page.keyboard.up("Alt");
  const moved = await vertexResponse; expect(moved.ok()).toBe(true);
  const parameters = moved.request().postDataJSON().command.parameters;
  const vertexPreview = expected.map((p, i): Vec2 => i === 0 ? [parameters.target_x_m, parameters.target_y_m] : p);
  same(ring(await view(request, id), surface), vertexPreview); await sameUI(page, surface, vertexPreview);
  const p = vertexPreview, length = Math.hypot(p[1][0] - p[0][0], p[1][1] - p[0][1]);
  const nx = (p[1][1] - p[0][1]) / length, ny = -(p[1][0] - p[0][0]) / length, off = 12 + Math.abs(nx) * 30 + Math.abs(ny) * 4;
  const midpoint = await point(page, (p[0][0] + p[1][0]) / 2, (p[0][1] + p[1][1]) / 2);
  await page.mouse.dblclick(midpoint[0] + nx * off, midpoint[1] - ny * off);
  const dimension = page.getByRole("textbox", { name: "Edge length in metres" }); await dimension.fill("18"); await dimension.press("Enter");
  const dimensionPreview = setEdgeLength(vertexPreview, 0, 18, "start");
  await expect.poll(async () => ring(await view(request, id), surface)).toEqual(dimensionPreview); await sameUI(page, surface, dimensionPreview);
  await field(page, request, id); const packed = await view(request, id);
  const positions = (packed.bundle.scene.module_instances as Array<{ module_instance_id: string; transform: { position_z_m: number } }>).map((m) => [m.module_instance_id, m.transform.position_z_m] as const);
  expect(positions.length).toBeGreaterThan(0);
  await page.keyboard.press("Alt+3"); await select(page, "S7b roof");
  const elevation = page.locator(".inspectorpane").getByLabel("Roof height"); await elevation.fill("1.5"); await elevation.press("Enter");
  await expect.poll(async () => (await view(request, id)).bundle.scene.surfaces[0].base_elevation_m).toBe(1.5);
  const raised = (await view(request, id)).bundle.scene.module_instances as Array<{ module_instance_id: string; transform: { position_z_m: number } }>;
  for (const [moduleId, z] of positions) expect(Math.abs(raised.find((m) => m.module_instance_id === moduleId)!.transform.position_z_m - z - 1.5)).toBeLessThanOrEqual(1e-9);
});

test("polygon roof fills through S7a, E persists, obstacle deletion preserves modules and offers re-fill", async ({ page, request }) => {
  const { id, name } = await create(request, "polygon and stale", false); await open(page, name);
  await page.keyboard.press("p"); for (const text of ["0,0", "20,0", "20,10", "0,10"]) await type(page, text); await page.keyboard.press("Enter");
  await expect.poll(async () => (await view(request, id)).bundle.scene.surfaces.length).toBe(1);
  const initialObstacle = await request.post(path(id) + "/obstacles/box", { data: { name: "Packing exclusion", origin_x_m: 8, origin_y_m: 3, width_m: 2, depth_m: 2, height_m: 2 } }); expect(initialObstacle.ok()).toBe(true);
  await open(page, name); await field(page, request, id); const packed = await view(request, id);
  const moduleIds = packed.bundle.scene.module_instances.map((m) => m.module_instance_id);
  await page.keyboard.press("Alt+3"); await page.keyboard.press("e");
  for (const text of ["25,0", "27,0", "26,2"]) await type(page, text); await page.keyboard.press("Enter");
  await expect.poll(async () => (await view(request, id)).bundle.scene.obstacles.length).toBe(2);
  expect((await view(request, id)).bundle.scene.obstacles.at(-1)!.obstacle_type).toBe("extruded_polygon");
  await select(page, "Packing exclusion"); await expect(page.locator(".taskpanel .layer--on")).toHaveText(/Packing exclusion/);
  await page.keyboard.press("Delete"); await expect(page.getByRole("alertdialog")).toContainText("Packing exclusion");
  await page.getByRole("alertdialog").getByRole("button", { name: "Delete", exact: true }).click();
  await expect.poll(async () => (await view(request, id)).bundle.scene.obstacles.length).toBe(1);
  expect((await view(request, id)).bundle.scene.module_instances.map((m) => m.module_instance_id)).toEqual(moduleIds);
  await page.keyboard.press("Alt+9"); await expect(page.getByText("Re-fill available", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Re-fill", exact: true }).click(); await expect(page.locator(".taskpanel").getByRole("button", { name: "Apply re-fill" })).toBeVisible();
});

test("support rotate/delete use the engine refusal; lowering into an obstacle reports conflicts without options", async ({ page, request }) => {
  const { id, name } = await create(request, "support guards"); await open(page, name); await field(page, request, id);
  const before = await view(request, id); const fieldId = before.bundle.scene.pv_fields[0].pv_field_id;
  const obstacle = await request.post(path(id) + "/obstacles/box", { data: { name: "Below modules", origin_x_m: 0, origin_y_m: 0, width_m: 20, depth_m: 10, base_elevation_m: -2, height_m: 1 } }); expect(obstacle.ok()).toBe(true);
  await open(page, name); await select(page, "S7b roof");
  const beforeRotate = await view(request, id);
  const refusal = page.waitForResponse((r) => r.url().endsWith("/scene/commands") && r.request().postDataJSON().command.command_type === "rotate");
  await page.keyboard.press("r"); await type(page, "10,5"); await type(page, "15");
  const rotated = await refusal; expect(rotated.status()).toBe(200);
  expect(rotated.request().postDataJSON()).toMatchObject({ dependent_fields: "apply", dry_run: true });
  const roofPreview = page.getByRole("alertdialog", { name: "Roof carries PV fields" });
  const rotateImpact = (await rotated.json()).dependent_fields[0]; expect(rotateImpact.pv_field_id).toBe(fieldId);
  await expect(roofPreview).toContainText(rotateImpact.name); await expect(roofPreview).toContainText(`Modules: ${rotateImpact.module_count_before} → ${rotateImpact.module_count_after}`); await expect(roofPreview).toContainText(`STC power: ${(rotateImpact.stc_power_w_before / 1000).toFixed(2)} → ${(rotateImpact.stc_power_w_after / 1000).toFixed(2)} kWp`);
  for (const stringId of rotateImpact.string_ids) await expect(roofPreview).toContainText(stringId);
  const committing: string[] = []; page.on("request", (r) => { if (r.method() === "POST" && r.url().endsWith("/scene/commands") && !r.postDataJSON().dry_run) committing.push(r.url()); });
  await roofPreview.getByRole("button", { name: "Cancel", exact: true }).click(); await expect(roofPreview).toBeHidden();
  expect(committing).toEqual([]); expect(await view(request, id)).toEqual(beforeRotate);
  const intact = await view(request, id);
  const targets = [intact.bundle.scene.surfaces[0].surface_id, intact.bundle.scene.obstacles[0].obstacle_id];
  await page.evaluate(async (ids) => (await import("/src/state/store.tsx")).uiStore.getState().dispatch({ type: "select", ids }), targets);
  await page.keyboard.press("Delete"); const deletion = page.getByRole("alertdialog");
  const deleteResponse = page.waitForResponse((r) => r.url().endsWith("/scene/commands") && r.request().postDataJSON().command.command_type === "delete");
  await deletion.getByRole("button", { name: "Delete roof and its 1 PV fields", exact: true }).click(); const deleted = await deleteResponse;
  expect(deleted.status()).toBe(200); expect(deleted.request().postDataJSON().command.target_entity_ids).toEqual(targets);
  expect(deleted.request().postDataJSON()).toMatchObject({ dependent_fields: "apply", dry_run: true });
  const deletePreview = page.getByRole("alertdialog", { name: "Roof carries PV fields" });
  await expect(deletePreview).toContainText(`Modules: ${before.bundle.scene.module_instances.length} → 0`); const deleteImpact = (await deleted.json()).dependent_fields[0];
  await expect(deletePreview).toContainText(deleteImpact.name);
  await expect(deletePreview).toContainText(`STC power: ${(deleteImpact.stc_power_w_before / 1000).toFixed(2)} → 0.00 kWp`);
  for (const stringId of deleteImpact.string_ids) await expect(deletePreview).toContainText(stringId);
  await deletePreview.getByRole("button", { name: "Cancel", exact: true }).click(); await expect(deletePreview).toBeHidden();
  expect(committing).toEqual([]); expect(await view(request, id)).toEqual(intact);
  await select(page, "S7b roof");
  const elevationResponse = page.waitForResponse((r) => r.url().endsWith("/scene/commands") && r.request().postDataJSON().command.command_type === "edit_elevation");
  await page.locator(".inspectorpane").getByLabel("Roof height").fill("-2"); await page.locator(".inspectorpane").getByLabel("Roof height").press("Enter");
  const lowered = await elevationResponse; expect(lowered.status()).toBe(422); const detail = (await lowered.json()).detail;
  expect(detail).not.toHaveProperty("options"); expect(detail.conflicts.length).toBeGreaterThan(0);
  const conflicts = page.getByRole("alertdialog", { name: "Geometry change refused" }); await expect(conflicts).toContainText(detail.message); await expect(conflicts).toContainText(detail.conflicts[0].module_instance_id);
  await expect(conflicts.getByRole("button", { name: "Remove modules under obstacle" })).toHaveCount(0);
  await conflicts.getByRole("button", { name: "Close", exact: true }).click();
  expect((await view(request, id)).bundle.scene.surfaces[0].base_elevation_m).toBe(0);
});
