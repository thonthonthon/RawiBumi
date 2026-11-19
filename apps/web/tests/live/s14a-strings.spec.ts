import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

// S14a on the real engine: split, join, reverse, move and swap from the plan tools, the engine's live checks in
// the string table, serpentine strings from the panel, and undo of every edit.
const API = process.env.RAWIBUMI_API;
if (!API || !/^http:\/\/127\.0\.0\.1:\d+$/.test(API) || API.endsWith(":8000")) throw new Error("S14a requires the disposable test API, never var/projects.");
const path = (id: string) => `${API}/api/projects/${id}`;

type Vec2 = [number, number];
type Bundle = { scene: { module_instances: Array<{ module_instance_id: string; pv_field_id: string; row_index: number; column_index: number }> }; electrical_design: { strings: Array<{ string_id: string; module_instance_ids: string[] }>; inverter_instances: Array<{ inverter_instance_id: string }> } };
type View = { bundle: Bundle; scene_view: { local_features: Array<{ id: string; polygon: Vec2[] }> }; topology_checks: { strings: Array<{ string_id: string; checks: Array<{ code: string; state: string; message: string }> }> } };
const getView = async (request: APIRequestContext, id: string): Promise<View> => (await request.get(path(id))).json();
const stringsOf = (v: View) => new Map(v.bundle.electrical_design.strings.map((s) => [s.string_id, s.module_instance_ids]));

async function setup(request: APIRequestContext, suffix: string, rows: number, length: number | null) {
  const catalog = await (await request.get(`${API}/api/catalog`)).json();
  const module = catalog.modules.find((m: { revision_id: string }) => m.revision_id === "mod-rawibumi-uat-550-r1");
  const name = `S14a ${suffix} ${Date.now()} ${Math.random()}`;
  const created = await request.post(`${API}/api/projects`, { data: { name, latitude_deg: -6.2, longitude_deg: 106.8, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" } });
  expect(created.ok()).toBe(true); const id: string = (await created.json()).bundle.project.project_id;
  const height = 1 + (rows - 1) * 3.2 + module.height_m * Math.cos(Math.PI / 18) + 0.05;
  const roof = await request.post(path(id) + "/surfaces/rectangle", { data: { name: "Strings roof", width_m: 1 + 10 * (module.width_m + 0.02) - 0.01, height_m: height, base_elevation_m: 0 } });
  const surface = (await roof.json()).bundle.scene.surfaces[0].surface_id;
  expect((await request.post(path(id) + "/pv-fields", { data: { name: "Strings field", support_surface_id: surface, module_definition_revision_id: module.revision_id, tilt_deg: 10, row_pitch_m: 3.2, module_gap_x_m: 0.02, perimeter_setback_m: 0.5, obstacle_setback_m: 0.3 } })).ok()).toBe(true);
  const inverter = await request.post(path(id) + "/inverters", { data: { inverter_definition_revision_id: "inv-rawibumi-uat-150k-r1", name: "INV-01" } });
  const inverterId = (await inverter.json()).bundle.electrical_design.inverter_instances[0].inverter_instance_id;
  if (length) {
    expect((await request.post(path(id) + "/strings", { data: { string_length: length, allow_shorter_remainder: false } })).ok()).toBe(true);
    expect((await request.post(path(id) + "/assignments", { data: { inverter_instance_id: inverterId } })).ok()).toBe(true);
  }
  return { id, name, initial: await getView(request, id) };
}
async function open(page: Page, name: string) {
  await page.goto("/"); await page.locator(".start__row", { hasText: name }).click(); await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+6"); await expect(page.getByRole("treegrid", { name: /Electrical topology/ })).toBeVisible();
}
async function at(page: Page, p: Vec2): Promise<Vec2> {
  const canvas = page.locator("canvas.plan__canvas");
  const [cx, cy, scale] = (await canvas.getAttribute("data-plan-view"))!.split(" ").map(Number);
  const box = (await canvas.boundingBox())!;
  return [box.x + (p[0] - cx) * scale + box.width / 2, box.y + box.height / 2 - (p[1] - cy) * scale];
}
function centre(v: View, moduleId: string): Vec2 {
  const polygon = v.scene_view.local_features.find((f) => f.id === moduleId)!.polygon;
  return [polygon.reduce((s, p) => s + p[0], 0) / polygon.length, polygon.reduce((s, p) => s + p[1], 0) / polygon.length];
}
const commands = (page: Page, id: string) => page.waitForResponse((r) => r.url().endsWith(`/projects/${id}/electrical/commands`) && r.request().method() === "POST");
async function gesture(page: Page, id: string, v: View, clicks: string[]) {
  const sent = commands(page, id);
  for (const m of clicks) await page.mouse.click(...await at(page, centre(v, m)));
  const response = await sent; expect(response.status(), await response.text()).toBe(200);
  return JSON.parse(response.request().postData()!).commands as Array<{ command_type: string; parameters: Record<string, unknown> }>;
}

test("split, join, reverse, move and swap on the engine, with the engine's live checks, then undo each", async ({ page, request }) => {
  const errors: string[] = []; page.on("pageerror", (e) => errors.push(e.message));
  const { id, name, initial } = await setup(request, "edits", 2, 10);
  const [s1, s2] = [stringsOf(initial).get("S001")!, stringsOf(initial).get("S002")!];
  expect([s1.length, s2.length]).toEqual([10, 10]);
  await open(page, name);
  await page.waitForTimeout(300); // let the plan fit the stage above the string table

  // Split (X) after the 4th module: S003 takes the other six; S001 at 4 × Vmp fails the MPPT window.
  await page.keyboard.press("x");
  expect((await gesture(page, id, initial, [s1[3]]))[0]).toMatchObject({ command_type: "split_string", parameters: { string_id: "S001", after_module_instance_id: s1[3] } });
  let v = await getView(request, id);
  expect(stringsOf(v).get("S001")).toEqual(s1.slice(0, 4)); expect(stringsOf(v).get("S003")).toEqual(s1.slice(4));
  const window = v.topology_checks.strings.find((s) => s.string_id === "S001")!.checks.find((c) => c.code === "voltage_window")!;
  expect(window.state).toBe("fail"); expect(window.message).toContain("window 200–1000 V");
  const row = page.locator(".stringtable tr", { hasText: "S001" });
  await expect(row.locator(".checkglyph--fail")).toHaveAttribute("aria-label", /window 200–1000 V/);

  // Join (J) S001 then S003: S001 is whole again and its glyph clears.
  await page.keyboard.press("j");
  await gesture(page, id, v, [s1[0], s1[6]]);
  v = await getView(request, id);
  expect(stringsOf(v).get("S001")).toEqual(s1); expect(stringsOf(v).has("S003")).toBe(false);
  await expect(row.locator(".checkglyph--fail")).toHaveCount(0);

  // Reverse (R).
  await page.keyboard.press("r");
  await gesture(page, id, v, [s2[0]]);
  v = await getView(request, id);
  expect(stringsOf(v).get("S002")).toEqual([...s2].reverse());

  // Move (M) S001's first module into S002 at the clicked module's place.
  await page.keyboard.press("m");
  const target = stringsOf(v).get("S002")!;
  const moved = await gesture(page, id, v, [s1[0], target[2]]);
  expect(moved[0]).toMatchObject({ command_type: "move_module", parameters: { module_instance_id: s1[0], to_string_id: "S002", index: 2 } });
  v = await getView(request, id);
  expect(stringsOf(v).get("S002")!.slice(0, 4)).toEqual([target[0], target[1], s1[0], target[2]]);

  // Swap (W) two modules of S001.
  await page.keyboard.press("w");
  await gesture(page, id, v, [s1[1], s1[9]]);
  v = await getView(request, id);
  expect(stringsOf(v).get("S001")![0]).toBe(s1[9]); expect(stringsOf(v).get("S001")!.at(-1)).toBe(s1[1]);

  // Five edits, five undo steps back to the start.
  for (let i = 0; i < 5; i++) {
    const undone = page.waitForResponse((r) => r.url().endsWith(`/projects/${id}/undo`));
    await page.keyboard.press("Control+z"); expect((await undone).status()).toBe(200);
  }
  await expect.poll(async () => stringsOf(await getView(request, id))).toEqual(stringsOf(initial));
  expect(errors).toEqual([]);
});

test("serpentine strings from the panel run back and forth along the rows", async ({ page, request }) => {
  const { id, name, initial } = await setup(request, "serpentine", 2, null);
  const modules = initial.bundle.scene.module_instances;
  expect(new Set(modules.map((m) => m.row_index)).size).toBe(2);
  await open(page, name);
  await page.locator(".taskpanel").getByRole("button", { name: "Rules", exact: true }).click();
  await page.locator(".taskpanel").getByLabel("Modules per string").fill(String(modules.length));
  await page.getByRole("radio", { name: "Serpentine", exact: true }).click();
  await expect(page.locator('.taskpanel .notwired[title*="serpentine"]')).toHaveCount(0);
  const sent = commands(page, id);
  await page.locator(".taskpanel").getByRole("button", { name: "Create strings", exact: true }).click();
  const response = await sent; expect(response.status(), await response.text()).toBe(200);
  expect(JSON.parse(response.request().postData()!).commands[0].parameters.ordering).toBe("serpentine");
  const [string] = (await getView(request, id)).bundle.electrical_design.strings;
  const byId = new Map(modules.map((m) => [m.module_instance_id, m]));
  const rows = string.module_instance_ids.map((m) => byId.get(m)!.row_index);
  const columns = string.module_instance_ids.map((m) => byId.get(m)!.column_index);
  const half = rows.findIndex((r) => r !== rows[0]);
  expect(rows.slice(half).every((r) => r !== rows[0])).toBe(true); // one turn, at the row end
  expect(columns[half]).toBe(columns[half - 1]); // the second row starts where the first ended
});
