import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import type { ModuleDeletePreview, ProjectView } from "../../src/types";
import type { Vec2 } from "../../src/geometry";

const API = process.env.RAWIBUMI_API;
if (!API || !/^http:\/\/127\.0\.0\.1:\d+$/.test(API) || API.endsWith(":8000")) throw new Error("S13b requires the isolated test launcher on a checked-free loopback port, never 8000 or var/projects.");
const url = (id: string) => `${API}/api/projects/${id}`;
async function view(request: APIRequestContext, id: string): Promise<ProjectView> { const r = await request.get(url(id)); expect(r.ok()).toBe(true); return r.json(); }
async function create(request: APIRequestContext) {
  const name = `S13b modules ${Date.now()} ${Math.random().toString(36).slice(2)}`;
  const r = await request.post(`${API}/api/projects`, { data: { name, latitude_deg: -6.2, longitude_deg: 106.8, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" } });
  expect(r.ok()).toBe(true); const id: string = (await r.json()).bundle.project.project_id;
  expect((await request.post(url(id) + "/surfaces/rectangle", { data: { name: "S13b roof", width_m: 20, height_m: 12, base_elevation_m: 6 } })).ok()).toBe(true);
  expect((await request.post(url(id) + "/obstacles/box", { data: { name: "S13b obstacle", origin_x_m: 16, origin_y_m: 8, width_m: 2, depth_m: 1, base_elevation_m: 6, height_m: 2 } })).ok()).toBe(true);
  const before = await view(request, id);
  expect((await request.post(url(id) + "/pv-fields", { data: { name: "S13b field", support_surface_id: before.bundle.scene.surfaces[0].surface_id,
    module_definition_revision_id: before.catalog.modules[0].revision_id, orientation: "portrait", azimuth_deg: 0, tilt_deg: 10,
    module_gap_x_m: .02, module_gap_y_m: .02, row_pitch_m: 3.1, mounting_height_m: .2, perimeter_setback_m: .7, obstacle_setback_m: .3 } })).ok()).toBe(true);
  expect((await request.post(url(id) + "/strings", { data: { string_length: 6, allow_shorter_remainder: true } })).ok()).toBe(true);
  return { id, name };
}
async function state(page: Page) { return page.evaluate(async () => (await import("/src/state/store.tsx")).uiStore.getState().state); }
async function open(page: Page, name: string) {
  await page.goto("/"); await page.locator(".start__row", { hasText: name }).click(); await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+4"); await expect(page.locator('.rail [aria-current="step"]')).toContainText("PV layout");
  await expect.poll(async () => (await state(page)).busy).toBeNull();
}
// Only the fixture's 20 x 12 roof defines the initial extent. No pan/zoom or live test hook is used.
async function point(page: Page, p: Vec2): Promise<Vec2> {
  return page.evaluate(([x, y]) => {
    const canvas = document.querySelector<HTMLCanvasElement>(".plan__canvas")!, r = canvas.getBoundingClientRect();
    const bar = document.querySelector<HTMLElement>(".plan__scalebar")!;
    const scale = parseFloat(bar.style.width) / parseFloat(bar.parentElement!.querySelector("span")!.textContent!);
    return [r.left + r.width / 2 + (x - 10) * scale, r.top + r.height / 2 - (y - 6) * scale];
  }, p);
}
type Placement = { module_instance_id: string; pv_field_id: string; transform: { position_x_m: number; position_y_m: number; position_z_m: number }; row_index: number; column_index: number };
function modules(v: ProjectView): Placement[] { return [...v.bundle.scene.module_instances as unknown as Placement[]].sort((a, b) => a.row_index - b.row_index || a.column_index - b.column_index); }
const centre = (m: Placement): Vec2 => [m.transform.position_x_m, m.transform.position_y_m];
async function clickModule(page: Page, m: Placement, shift = false) {
  if (shift) await page.keyboard.down("Shift"); await page.mouse.click(...await point(page, centre(m))); if (shift) await page.keyboard.up("Shift");
}
function response(page: Page, command: string, dry = false) {
  return page.waitForResponse((r) => r.url().endsWith("/pv-fields/modules/commands") && r.request().method() === "POST" &&
    r.request().postDataJSON().command === command && !!r.request().postDataJSON().dry_run === dry);
}

test("box deletion previews the independent impact and confirms exact module and whole-string removal", async ({ page, request }) => {
  const { id, name } = await create(request); await open(page, name); const before = await view(request, id);
  const chosen = modules(before).slice(0, 2), ids = chosen.map((m) => m.module_instance_id);
  const polygon = before.scene_view.local_features.filter((f) => ids.includes(f.id)).flatMap((f) => f.polygon);
  const a: Vec2 = [Math.min(...polygon.map((p) => p[0])) - .1, Math.min(...polygon.map((p) => p[1])) - .1];
  const b: Vec2 = [Math.max(...polygon.map((p) => p[0])) + .1, Math.max(...polygon.map((p) => p[1])) + .1];
  await page.mouse.move(...await point(page, a)); await page.mouse.down(); await page.mouse.move(...await point(page, b), { steps: 6 }); await page.mouse.up();
  await expect.poll(async () => (await state(page)).selection.slice().sort()).toEqual([...ids].sort());
  const previewResponse = response(page, "delete_modules", true); await page.keyboard.press("Delete");
  const preview = await previewResponse; expect(preview.status()).toBe(200); const impact = await preview.json() as ModuleDeletePreview;
  const strings = before.bundle.electrical_design.strings.filter((s) => s.module_instance_ids.some((mid) => ids.includes(mid))).map((s) => s.string_id).sort();
  expect(impact.string_ids).toEqual(strings);
  const total = before.bundle.scene.module_instances.length, watts = before.catalog.modules[0].pmp_w;
  expect(impact.fields[0]).toMatchObject({ module_count_before: total, module_count_after: total - ids.length, stc_power_w_before: total * watts, stc_power_w_after: (total - ids.length) * watts });
  const dialog = page.getByRole("alertdialog", { name: "Delete selected modules?" });
  await expect(dialog).toContainText(`Modules: ${total} → ${total - ids.length}`);
  await expect(dialog).toContainText(`STC power: ${(total * watts / 1000).toFixed(2)} → ${((total - ids.length) * watts / 1000).toFixed(2)} kWp`);
  for (const sid of strings) await expect(dialog).toContainText(sid);
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click(); await expect(dialog).toBeHidden(); expect(await view(request, id)).toEqual(before);
  const second = response(page, "delete_modules", true); await page.locator(".inspectorpane").getByRole("button", { name: "Delete 2 modules", exact: true }).click(); await second;
  const committed = response(page, "delete_modules"); await dialog.getByRole("button", { name: "Confirm module deletion" }).click();
  const saved = await committed; expect(saved.status()).toBe(200);
  expect(saved.request().postDataJSON()).toEqual({ command: "delete_modules", module_instance_ids: preview.request().postDataJSON().module_instance_ids, discard_dependent_strings: true });
  await expect(dialog).toBeHidden(); const after = await view(request, id);
  expect(after.bundle.scene.module_instances).toEqual(before.bundle.scene.module_instances.filter((m) => !ids.includes(m.module_instance_id)));
  expect(after.bundle.electrical_design.strings).toEqual(before.bundle.electrical_design.strings.filter((s) => !strings.includes(s.string_id)));
  expect(after.bundle.scene.pv_fields[0].layout_status).toBe("manual");
  expect(after.bundle.project.project_revision.revision_number).toBe(before.bundle.project.project_revision.revision_number + 1);
  await expect.poll(async () => (await state(page)).selection).toEqual([]);
});

test("group drag and nudge preserve identity and strings; dragging one module onto the obstacle is atomically refused", async ({ page, request }) => {
  const { id, name } = await create(request); await open(page, name); const before = await view(request, id);
  const placed = modules(before), lastRow = Math.max(...placed.map((m) => m.row_index));
  const chosen = placed.filter((m) => m.row_index === lastRow).slice(0, 2), ids = chosen.map((m) => m.module_instance_id);
  await clickModule(page, chosen[0]); await clickModule(page, chosen[1], true);
  const a = centre(chosen[0]), moved = response(page, "move_modules");
  await page.mouse.move(...await point(page, a)); await page.mouse.down(); await page.keyboard.down("Shift");
  await page.mouse.move(...await point(page, [a[0], a[1] + .54]), { steps: 6 }); await page.mouse.up(); await page.keyboard.up("Shift");
  const result = await moved; expect(result.status()).toBe(200); expect(result.request().postDataJSON()).toEqual({ command: "move_modules", module_instance_ids: ids, dx_m: 0, dy_m: .5 });
  await expect.poll(async () => (await state(page)).busy).toBeNull(); let after = await view(request, id);
  for (const old of placed) {
    const now = modules(after).find((m) => m.module_instance_id === old.module_instance_id)!;
    expect(now.pv_field_id).toBe(old.pv_field_id); expect(now.transform.position_x_m).toBeCloseTo(old.transform.position_x_m, 9);
    expect(now.transform.position_y_m).toBeCloseTo(old.transform.position_y_m + (ids.includes(old.module_instance_id) ? .5 : 0), 9);
  }
  expect(after.bundle.electrical_design).toEqual(before.bundle.electrical_design);
  await expect.poll(async () => (await state(page)).selection).toEqual(ids);
  const nudged = response(page, "move_modules"); await page.keyboard.press("ArrowUp"); expect((await nudged).status()).toBe(200);
  await expect.poll(async () => (await state(page)).busy).toBeNull(); after = await view(request, id);
  for (const old of chosen) expect(modules(after).find((m) => m.module_instance_id === old.module_instance_id)!.transform.position_y_m).toBeCloseTo(old.transform.position_y_m + .6, 9);
  const moving = modules(after).find((m) => m.module_instance_id === ids[0])!;
  await page.keyboard.press("Escape"); await clickModule(page, moving);
  const refused = response(page, "move_modules"); await page.mouse.move(...await point(page, centre(moving))); await page.mouse.down();
  await page.mouse.move(...await point(page, [17, 8.5]), { steps: 6 }); await page.mouse.up();
  const failure = await refused; expect(failure.status()).toBe(422);
  const detail = (await failure.json()).detail; expect(detail.conflicts.some((c: { code: string }) => c.code === "module_obstacle_overlap")).toBe(true);
  const fillDialog = page.getByRole("alertdialog", { name: "These modules don't fit exactly there. Fit into this space?" });
  await expect(fillDialog).toContainText("1 module would overlap obstacle S13b obstacle");
  await fillDialog.getByRole("button", { name: "Cancel", exact: true }).click(); await expect(fillDialog).toBeHidden();
  await expect.poll(async () => (await state(page)).busy).toBeNull();
  expect(await view(request, id)).toEqual(after);
});
