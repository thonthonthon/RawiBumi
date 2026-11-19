import { expect, test, type APIRequestContext } from "@playwright/test";

// F5 gate (plan C2): "create and assign work live on the existing routes".
// Rules (POST /strings) and automatic assignment (POST /assignments)
// go to the engine through the topology command adapter; the commands that
// need proposal 0004 say so instead of changing anything locally.

const API = process.env.RAWIBUMI_API ?? "http://127.0.0.1:8000";

interface View {
  bundle: {
    project: { project_id: string };
    scene: { surfaces: Array<{ surface_id: string }>; module_instances: Array<{ module_instance_id: string }> };
    electrical_design: {
      inverter_instances: Array<{ inverter_instance_id: string; mppt_instance_ids: string[] }>;
      strings: Array<{ string_id: string; module_instance_ids: string[]; target_mppt_instance_id: string | null }>;
    };
  };
}

async function project(api: APIRequestContext, id: string): Promise<View> {
  const r = await api.get(`${API}/api/projects/${id}`);
  expect(r.ok()).toBe(true);
  return (await r.json()) as View;
}

test("uniform strings and auto-assign go through the engine's routes; new commands report the missing route", async ({ page, request }) => {
  const health = await request.get(`${API}/api/health`).catch(() => null);
  test.skip(!health?.ok(), `Engine API not reachable at ${API}`);
  const catalog = (await (await request.get(`${API}/api/catalog`)).json()) as { modules: Array<{ revision_id: string }>; inverters: Array<{ revision_id: string }> };

  // Setup through the API: one roof, one PV field, one inverter.
  const name = `F5 live ${Date.now()}`;
  const created = await request.post(`${API}/api/projects`, {
    data: { name, latitude_deg: -6.9, longitude_deg: 107.6, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" }
  });
  expect(created.ok()).toBe(true);
  const id = ((await created.json()) as View).bundle.project.project_id;
  let v = (await (await request.post(`${API}/api/projects/${id}/surfaces/rectangle`, { data: { name: "Roof", width_m: 12, height_m: 6, base_elevation_m: 6 } })).json()) as View;
  const surface = v.bundle.scene.surfaces[0].surface_id;
  const field = await request.post(`${API}/api/projects/${id}/pv-fields`, {
    data: { name: "Live field", support_surface_id: surface, module_definition_revision_id: catalog.modules[0].revision_id, tilt_deg: 10, row_pitch_m: 2.6 }
  });
  expect(field.ok()).toBe(true);
  const inv = await request.post(`${API}/api/projects/${id}/inverters`, { data: { inverter_definition_revision_id: catalog.inverters[0].revision_id, name: "INV-01" } });
  expect(inv.ok()).toBe(true);
  v = await project(request, id);
  const modules = v.bundle.scene.module_instances.length;
  expect(modules).toBeGreaterThan(1);
  expect(v.bundle.electrical_design.strings).toHaveLength(0);

  // UI: electrical step, uniform strings → POST /strings.
  await page.goto("/");
  await page.getByText(name).first().click();
  await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+6");
  await expect(page.locator('.rail [aria-current="step"]')).toContainText("Electrical");
  const p = page.locator(".taskpanel");
  await p.getByRole("button", { name: "Rules" }).click();
  const len = Math.max(1, Math.floor(modules / 2));
  await p.getByLabel("Modules per string").fill(String(len));
  await p.getByLabel("Allow a shorter remainder string").check();
  await p.getByRole("button", { name: "Create strings" }).click();
  await expect.poll(async () => (await project(request, id)).bundle.electrical_design.strings.length).toBeGreaterThan(0);
  v = await project(request, id);
  expect(v.bundle.electrical_design.strings.every((s) => s.target_mppt_instance_id === null)).toBe(true);
  expect(v.bundle.electrical_design.strings.reduce((t, s) => t + s.module_instance_ids.length, 0)).toBe(modules);
  await expect(page.getByRole("treegrid", { name: /Electrical topology/ })).toContainText("Unassigned");

  // Auto-assign → POST /assignments.
  await p.getByRole("button", { name: /Assign unassigned/ }).click();
  await expect.poll(async () => (await project(request, id)).bundle.electrical_design.strings.every((s) => s.target_mppt_instance_id !== null)).toBe(true);
  v = await project(request, id);
  const mppts = new Set(v.bundle.electrical_design.inverter_instances[0].mppt_instance_ids);
  expect(v.bundle.electrical_design.strings.every((s) => mppts.has(s.target_mppt_instance_id!))).toBe(true);
  // The notation shows what the engine has: one entry per MPPT, the string lengths in it.
  const total = v.bundle.electrical_design.strings.reduce((t, s) => t + s.module_instance_ids.length, 0);
  let notation = "";
  await expect.poll(async () => {
    notation = await p.getByLabel("MPPT layout").inputValue();
    return notation.split(/[;,]/).map((x) => Number(x.trim()) || 0).reduce((a, b) => a + b, 0);
  }).toBe(total);
  expect(notation.split(";").length).toBe(mppts.size);

  // F6: the SLD draws the engine's own topology: one string node per string, wired to its MPPT input.
  await page.getByRole("button", { name: "SLD", exact: true }).click();
  for (const s of v.bundle.electrical_design.strings) {
    await expect(page.locator(`[data-node="str:${s.string_id}"]`)).toBeVisible();
    await expect(page.locator(`[data-wire="w:str:${s.string_id}"]`)).toHaveCount(1);
  }
  await expect(page.locator(`[data-node="inv:${v.bundle.electrical_design.inverter_instances[0].inverter_instance_id}"]`)).toBeVisible();
  await page.getByRole("button", { name: "Top", exact: true }).click();

  // Unassign persists through S5, disables only the selected string and discloses its excluded modules.
  const before = v.bundle.electrical_design.strings;
  const selected = before[0];
  await page.locator(".stringtable tbody tr").first().click(); // selects the string's modules
  await p.getByRole("button", { name: "Unassign", exact: true }).click();
  await expect.poll(async () => {
    const item = (await project(request, id)).bundle.electrical_design.strings.find((s) => s.string_id === selected.string_id) as typeof selected & { enabled: boolean };
    return [item.target_mppt_instance_id, item.enabled];
  }).toEqual([null, false]);
  const after = (await project(request, id)).bundle.electrical_design.strings;
  expect(after.filter((s) => s.string_id !== selected.string_id)).toEqual(before.filter((s) => s.string_id !== selected.string_id));
  const readiness = await request.get(`${API}/api/projects/${id}/execution-readiness`); expect(readiness.ok()).toBe(true);
  const excluded = (await readiness.json()).findings.find((f: { rule_id: string }) => f.rule_id === "MODULES_NOT_SIMULATED");
  expect(excluded.context.by_reason.string_unassigned).toBe(selected.module_instance_ids.length);
});
