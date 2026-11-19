import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import type { ProjectView } from "../../src/types";
import type { Vec2 } from "../../src/geometry";

const API = process.env.RAWIBUMI_API;
if (!API || !/^http:\/\/127\.0\.0\.1:\d+$/.test(API) || API.endsWith(":8000"))
  throw new Error("S13a requires the test-only launcher on a checked-free loopback port, never 8000 or var/projects.");
const url = (id: string) => `${API}/api/projects/${id}`;
async function view(request: APIRequestContext, id: string): Promise<ProjectView> {
  const r = await request.get(url(id)); expect(r.ok()).toBe(true); return r.json();
}
async function create(request: APIRequestContext) {
  const name = `S13a selection ${Date.now()} ${Math.random().toString(36).slice(2)}`;
  const r = await request.post(`${API}/api/projects`, { data: { name, latitude_deg: -6.2, longitude_deg: 106.8, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" } });
  expect(r.ok()).toBe(true); const id: string = (await r.json()).bundle.project.project_id;
  expect((await request.post(url(id) + "/surfaces/rectangle", { data: { name: "S13a roof", width_m: 20, height_m: 10, base_elevation_m: 6 } })).ok()).toBe(true);
  expect((await request.post(url(id) + "/obstacles/box", { data: { name: "S13a AHU", origin_x_m: 17, origin_y_m: 7, width_m: 2, depth_m: 1, base_elevation_m: 6, height_m: 2 } })).ok()).toBe(true);
  const initial = await view(request, id), surface = initial.bundle.scene.surfaces[0].surface_id;
  const fill = await request.post(url(id) + "/pv-fields", { data: {
    name: "S13a field", support_surface_id: surface, module_definition_revision_id: initial.catalog.modules[0].revision_id,
    orientation: "portrait", azimuth_deg: 15, tilt_deg: 10, module_gap_x_m: .02, module_gap_y_m: .02,
    row_pitch_m: 3.1, mounting_height_m: .2, perimeter_setback_m: .7, obstacle_setback_m: .6
  } });
  expect(fill.ok()).toBe(true); return { id, name, surface };
}
async function state(page: Page) {
  return page.evaluate(async () => (await import("/src/state/store.tsx")).uiStore.getState().state);
}
async function open(page: Page, name: string) {
  await page.goto("/"); await page.locator(".start__row", { hasText: name }).click();
  await expect(page.locator(".rail")).toBeVisible(); await page.keyboard.press("Alt+3");
  await expect(page.locator(".toollist")).toBeVisible(); await expect.poll(async () => (await state(page)).busy).toBeNull();
}
// The fixture's extent is its 20 x 10 roof; no pan or zoom. No live picking hook is added.
async function point(page: Page, p: Vec2): Promise<Vec2> {
  return page.evaluate(([x, y]) => {
    const canvas = document.querySelector<HTMLCanvasElement>(".plan__canvas")!, rect = canvas.getBoundingClientRect();
    const bar = document.querySelector<HTMLElement>(".plan__scalebar")!;
    const scale = parseFloat(bar.style.width) / parseFloat(bar.parentElement!.querySelector("span")!.textContent!);
    return [rect.left + rect.width / 2 + (x - 10) * scale, rect.top + rect.height / 2 - (y - 5) * scale];
  }, p);
}
async function typed(page: Page, value: string) { await page.keyboard.type(value); await page.keyboard.press("Enter"); }

test("Move commits once; later roof and blank clicks send no commands and preserve the revision", async ({ page, request }) => {
  const { id, name, surface } = await create(request); await open(page, name);
  const before = await view(request, id), commands: string[] = [];
  page.on("request", (r) => { if (r.method() === "POST" && /\/scene\/(commands|move)$/.test(new URL(r.url()).pathname)) commands.push(r.url()); });
  await page.locator(".taskpanel .layer__name", { hasText: "S13a AHU" }).click();
  await page.keyboard.press("m"); await typed(page, "17,7"); await typed(page, "@6,0");
  await expect.poll(async () => (await view(request, id)).bundle.project.project_revision.revision_number).toBe(before.bundle.project.project_revision.revision_number + 1);
  await expect.poll(async () => (await state(page)).busy).toBeNull();
  expect((await state(page)).tool).toBe("select");
  const saved = await view(request, id);
  await page.mouse.click(...await point(page, [19, 1])); await expect.poll(async () => (await state(page)).selection).toEqual([surface]);
  await page.mouse.click(...await point(page, [-1, -1])); await expect.poll(async () => (await state(page)).selection).toEqual([]);
  expect(commands).toHaveLength(1); expect(await view(request, id)).toEqual(saved);
});

test("PV-layout window selects exactly the independently transformed module footprints, never the enclosing roof", async ({ page, request }) => {
  const { id, name } = await create(request); await open(page, name); await page.keyboard.press("Alt+4");
  const before = await view(request, id), a: Vec2 = [.4, .4], b: Vec2 = [9.8, 5];
  type RawModule = { module_instance_id: string; pv_field_id: string; module_definition_revision_id: string; transform: { position_x_m: number; position_y_m: number; rotation_z_deg: number } };
  const modules = before.bundle.scene.module_instances as unknown as RawModule[];
  // Independent oracle: component dimensions -> portrait/landscape -> tilt projection -> clockwise rotation -> translation.
  // Do not use local_features polygons, boxSelect, ModuleIndex or UI module geometry.
  const expected = modules.filter((m) => {
    const field = before.bundle.scene.pv_fields.find((f) => f.pv_field_id === m.pv_field_id)!;
    const definition = before.catalog.modules.find((d) => d.revision_id === m.module_definition_revision_id)!;
    const portrait = field.orientation === "portrait";
    const w = portrait ? definition.width_m : definition.height_m;
    const h = (portrait ? definition.height_m : definition.width_m) * Math.cos(field.tilt_deg * Math.PI / 180);
    const angle = m.transform.rotation_z_deg * Math.PI / 180, c = Math.cos(angle), s = Math.sin(angle);
    return [[-w / 2, -h / 2], [w / 2, -h / 2], [w / 2, h / 2], [-w / 2, h / 2]].every(([x, y]) => {
      const px = m.transform.position_x_m + x * c + y * s;
      const py = m.transform.position_y_m - x * s + y * c;
      return px > a[0] && px < b[0] && py > a[1] && py < b[1];
    });
  }).map((m) => m.module_instance_id).sort();
  expect(expected.length).toBeGreaterThan(0); expect(expected.length).toBeLessThan(modules.length);
  const edits: string[] = [];
  page.on("request", (r) => { if (["POST", "PATCH", "DELETE"].includes(r.method())) edits.push(r.url()); });
  await page.mouse.move(...await point(page, a)); await page.mouse.down();
  await page.mouse.move(...await point(page, b), { steps: 6 }); await page.mouse.up();
  await expect.poll(async () => (await state(page)).selection.slice().sort()).toEqual(expected);
  const power = before.catalog.modules[0].pmp_w * expected.length / 1000;
  await expect(page.locator(".inspectorpane")).toContainText(`${power.toFixed(2)} kWp`);
  expect(edits).toEqual([]); expect(await view(request, id)).toEqual(before);
});
