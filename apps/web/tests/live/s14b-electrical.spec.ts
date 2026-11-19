import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { openSection } from "../e2e/sections";

// S14b on the real engine: a within-tolerance mixed MPPT passes preflight; a tighter tolerance and an override with a
// reason (the run stays blocked, and says why); pairing chips and notation Apply; replicate on explicit tables.
const API = process.env.RAWIBUMI_API;
if (!API || !/^http:\/\/127\.0\.0\.1:\d+$/.test(API) || API.endsWith(":8000")) throw new Error("S14b requires the disposable test API, never var/projects.");
const path = (id: string) => `${API}/api/projects/${id}`;
const MODULE = "mod-rawibumi-uat-550-r1", INVERTER = "inv-rawibumi-uat-150k-r1";

type Vec2 = [number, number];
type View = {
  bundle: {
    scene: { pv_fields: Array<{ pv_field_id: string; name: string }>; module_instances: Array<{ module_instance_id: string; pv_field_id: string; table_id?: string; column_index: number }> };
    electrical_design: { strings: Array<{ string_id: string; module_instance_ids: string[]; target_mppt_instance_id: string | null }>; inverter_instances: Array<{ inverter_instance_id: string; paired_pv_field_ids?: string[] }>;
      mppt_instances: Array<{ mppt_instance_id: string; index: number }>; orientation_policy?: { normal_angle_tolerance_deg?: number; overrides?: Array<{ mppt_instance_id: string; reason: string }> } };
  };
  scene_view: { local_features: Array<{ id: string; polygon: Vec2[] }> };
  topology_checks: { strings: Array<{ string_id: string; checks: Array<{ code: string; state: string; message: string }> }> };
};
const getView = async (request: APIRequestContext, id: string): Promise<View> => (await request.get(path(id))).json();
const electrical = (page: Page, id: string) => page.waitForResponse((r) => r.url().endsWith(`/projects/${id}/electrical/commands`) && r.request().method() === "POST" && r.request().postDataJSON().dry_run !== true);
const sent = async (response: Awaited<ReturnType<typeof electrical>>) => {
  expect(response.status(), await response.text()).toBe(200);
  return JSON.parse(response.request().postData()!).commands[0] as { command_type: string; parameters: Record<string, unknown> };
};
const cmd = (command_type: string, parameters: Record<string, unknown>) => ({ schema_name: "ElectricalTopologyCommand", schema_version: "0.1", command_id: `${command_type}-${Math.random()}`, command_type, parameters });
async function commands(request: APIRequestContext, id: string, ...list: ReturnType<typeof cmd>[]) {
  const r = await request.post(path(id) + "/electrical/commands", { data: { commands: list } }); expect(r.ok(), await r.text()).toBe(true);
}
async function project(request: APIRequestContext, suffix: string) {
  const name = `S14b ${suffix} ${Date.now()} ${Math.random()}`;
  const created = await request.post(`${API}/api/projects`, { data: { name, latitude_deg: -6.2, longitude_deg: 106.8, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" } });
  expect(created.ok()).toBe(true);
  return { id: (await created.json()).bundle.project.project_id as string, name };
}
async function roofWithField(request: APIRequestContext, id: string, name: string, y: number, tilt: number, count = 10) {
  const roof = await request.post(path(id) + "/surfaces/rectangle", { data: { name, origin_x_m: 0, origin_y_m: y, width_m: 1 + count * 1.154 - 0.01, height_m: 3.45, base_elevation_m: 6.1 } });
  expect(roof.ok(), await roof.text()).toBe(true);
  const surface = (await roof.json()).bundle.scene.surfaces.find((s: { name: string }) => s.name === name).surface_id;
  const field = await request.post(path(id) + "/pv-fields", { data: { name: `${name} field`, support_surface_id: surface, module_definition_revision_id: MODULE, tilt_deg: tilt, row_pitch_m: 3.2, perimeter_setback_m: 0.5 } });
  expect(field.ok(), await field.text()).toBe(true);
}
async function inverter(request: APIRequestContext, id: string) {
  expect((await request.post(path(id) + "/inverters", { data: { inverter_definition_revision_id: INVERTER, name: "INV-01" } })).ok()).toBe(true);
}
async function open(page: Page, name: string) {
  await page.goto("/"); await page.locator(".start__row", { hasText: name }).click(); await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+6"); await expect(page.getByRole("treegrid", { name: /Electrical topology/ })).toBeVisible();
}
const orientation = (v: View, sid: string) => v.topology_checks.strings.find((s) => s.string_id === sid)!.checks.find((c) => c.code === "orientation")!;

test("a 0.5° mixed MPPT is ready; a 0.25° tolerance splits it, and an override with a reason silences the warning but keeps the run simulated", async ({ page, request }) => {
  const errors: string[] = []; page.on("pageerror", (e) => errors.push(e.message));
  const { id, name } = await project(request, "orientation");
  await roofWithField(request, id, "Roof A", 0, 10); await roofWithField(request, id, "Roof B", 20, 10.5); await inverter(request, id);
  let v = await getView(request, id);
  const [fa, fb] = v.bundle.scene.pv_fields.map((f) => f.pv_field_id);
  const of = (f: string) => v.bundle.scene.module_instances.filter((m) => m.pv_field_id === f).map((m) => m.module_instance_id);
  const mppt = v.bundle.electrical_design.mppt_instances.find((m) => m.index === 1)!.mppt_instance_id;
  await commands(request, id, cmd("create_string", { string_id: "S001", module_instance_ids: of(fa) }), cmd("create_string", { string_id: "S002", module_instance_ids: of(fb) }),
    cmd("assign_strings_to_mppt", { mppt_instance_id: mppt, string_ids: ["S001", "S002"] }));
  const mixed = async () => (await (await request.get(path(id) + "/execution-readiness")).json()).findings.filter((f: { rule_id: string }) => f.rule_id === "SIMULATION_SCOPE_MIXED_STRINGS_ON_ONE_MPPT");
  expect(await mixed()).toEqual([]);
  expect(orientation(await getView(request, id), "S002").state).toBe("pass");

  await open(page, name);
  await expect(page.locator(".taskpanel .notwired")).toHaveCount(0);
  await openSection(page, "Rules");
  const tolerance = page.locator(".taskpanel [data-orientation-tolerance] input");
  await expect(tolerance).toHaveValue("1");
  let response = electrical(page, id);
  await tolerance.fill("0.25"); await tolerance.press("Enter");
  expect(await sent(await response)).toMatchObject({ command_type: "set_orientation_tolerance", parameters: { tolerance_deg: 0.25 } });
  v = await getView(request, id);
  expect(orientation(v, "S002").state).toBe("warn");
  expect(await mixed()).toEqual([]);

  await page.locator(".taskpanel").getByRole("checkbox", { name: "Override orientation rule for MPPT 1" }).first().check();
  response = electrical(page, id);
  const reason = page.locator(".taskpanel").getByLabel("Override reason for MPPT 1").first();
  await reason.fill("Roofs A and B are one plane within survey tolerance"); await reason.press("Enter");
  expect(await sent(await response)).toMatchObject({ command_type: "set_orientation_override", parameters: { mppt_instance_id: mppt, reason: "Roofs A and B are one plane within survey tolerance" } });
  v = await getView(request, id);
  expect(orientation(v, "S002")).toEqual({ code: "orientation", state: "pass", message: "Mixed orientation accepted by override: Roofs A and B are one plane within survey tolerance" });
  expect(await mixed()).toEqual([]);
  await expect(page.locator(".taskpanel")).toContainText("Accepted; this MPPT is simulated with its mixed orientations.");

  // Two undo steps: the override, then the tolerance.
  for (let i = 0; i < 2; i++) {
    const undone = page.waitForResponse((r) => r.url().endsWith(`/projects/${id}/undo`));
    await page.locator(".stage").click({ position: { x: 5, y: 60 } });
    await page.keyboard.press("Control+z"); expect((await undone).status()).toBe(200);
  }
  await expect.poll(async () => (await getView(request, id)).bundle.electrical_design.orientation_policy?.normal_angle_tolerance_deg ?? 1).toBe(1);
  expect(await mixed()).toEqual([]);
  expect(errors).toEqual([]);
});

test("pairing chips and notation Apply draw strings from the paired field", async ({ page, request }) => {
  const { id, name } = await project(request, "apply");
  await roofWithField(request, id, "Roof A", 0, 10); await roofWithField(request, id, "Roof B", 20, 10); await inverter(request, id);
  const fields = (await getView(request, id)).bundle.scene.pv_fields;
  await open(page, name);
  const chip = page.locator(".taskpanel .chips").first().getByRole("button", { name: new RegExp(`^${fields[1].name}`) });
  let response = electrical(page, id);
  await chip.click();
  const pairing = await sent(await response);
  expect(pairing.command_type).toBe("set_inverter_pairing");
  expect(pairing.parameters.pv_field_ids).toEqual([fields[1].pv_field_id]);
  await expect(chip).toHaveAttribute("aria-pressed", "true");

  response = electrical(page, id);
  await page.locator(".taskpanel").getByLabel("MPPT layout").first().fill("10 ; 0");
  await page.locator(".taskpanel").getByRole("button", { name: "Apply layout" }).first().click();
  const apply = await sent(await response);
  expect(apply).toMatchObject({ command_type: "apply_mppt_layout", parameters: { layout: [[10], [0]], pv_field_ids: [fields[1].pv_field_id] } });
  const v = await getView(request, id);
  const [string] = v.bundle.electrical_design.strings;
  const fieldOf = new Map(v.bundle.scene.module_instances.map((m) => [m.module_instance_id, m.pv_field_id]));
  expect(new Set(string.module_instance_ids.map((m) => fieldOf.get(m)))).toEqual(new Set([fields[1].pv_field_id]));
  expect(string.target_mppt_instance_id).toBeTruthy();
  await expect(page.locator(".taskpanel").getByLabel("MPPT layout").first()).toHaveValue(/^10/);
});

test("replicate copies an explicit table's wiring to the identical table", async ({ page, request }) => {
  const { id, name } = await project(request, "replicate");
  const table = (table_id: string, x: number) => ({ table_id, anchor_xyz_m: [x, 0, 3], anchor_convention: "lower_left", tilt_deg: 10, azimuth_deg: 180, module_definition_revision_id: MODULE,
    modules_across: 6, modules_up: 1, module_orientation: "portrait", module_gap_across_m: 0.02, module_gap_up_m: 0.02 });
  const geometry = await request.post(path(id) + "/scene/geometry", { data: { operations: [{ operation_id: "tables", operation_type: "create_explicit_field", pv_field_id: "tables", name: "Explicit tables",
    tables: [table("T1", 0), table("T2", 10)], provenance: { source_id: "s14b-live" } }] } });
  expect(geometry.ok(), await geometry.text()).toBe(true);
  let v = await getView(request, id);
  const t1 = v.bundle.scene.module_instances.filter((m) => m.table_id === "T1").sort((a, b) => a.column_index - b.column_index).map((m) => m.module_instance_id);
  await commands(request, id, cmd("create_string", { string_id: "S001", module_instance_ids: [...t1].reverse() }));
  await open(page, name);
  v = await getView(request, id);
  // Select a module of T1 on the plan.
  const canvas = page.locator("canvas.plan__canvas");
  await page.waitForTimeout(300);
  const [cx, cy, scale] = (await canvas.getAttribute("data-plan-view"))!.split(" ").map(Number);
  const box = (await canvas.boundingBox())!;
  const poly = v.scene_view.local_features.find((f) => f.id === t1[2])!.polygon;
  const c: Vec2 = [poly.reduce((s, p) => s + p[0], 0) / poly.length, poly.reduce((s, p) => s + p[1], 0) / poly.length];
  await page.keyboard.press("v");
  await page.mouse.click(box.x + (c[0] - cx) * scale + box.width / 2, box.y + box.height / 2 - (c[1] - cy) * scale);
  const replicate = page.locator(".taskpanel").getByRole("button", { name: "Replicate pattern", exact: true });
  await expect(replicate).toBeEnabled();
  const response = electrical(page, id);
  await replicate.click();
  expect(await sent(await response)).toMatchObject({ command_type: "replicate_pattern", parameters: { source_pv_field_id: "tables", source_table_id: "T1" } });
  v = await getView(request, id);
  const t2 = v.bundle.scene.module_instances.filter((m) => m.table_id === "T2").sort((a, b) => a.column_index - b.column_index).map((m) => m.module_instance_id);
  const copy = v.bundle.electrical_design.strings.find((s) => s.string_id !== "S001")!;
  expect(copy.module_instance_ids).toEqual([...t2].reverse());
});
