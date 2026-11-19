import { expect, test, type Page } from "@playwright/test";

// USE3b on the real engine: two unstrung modules are added to a string from the right-click menu (one commit), and
// Re-fill with nothing changed previews a re-pack of the field on its current roof.
const API = process.env.RAWIBUMI_API;
if (!API || !/^http:\/\/127\.0\.0\.1:\d+$/.test(API) || API.endsWith(":8000")) throw new Error("USE3b requires the disposable test API, never var/projects.");
/** Page coordinates of a plan point, from the canvas's published view (as in the UX2 live spec). */
async function at(page: Page, p: [number, number]): Promise<[number, number]> {
  const canvas = page.locator("canvas.plan__canvas");
  const [cx, cy, scale] = (await canvas.getAttribute("data-plan-view"))!.split(" ").map(Number);
  const box = (await canvas.boundingBox())!;
  return [box.x + (p[0] - cx) * scale + box.width / 2, box.y + box.height / 2 - (p[1] - cy) * scale];
}

test("unstrung modules join a string from the menu; an unchanged Re-fill previews a re-pack", async ({ page, request }) => {
  const errors: string[] = []; page.on("pageerror", (e) => errors.push(e.message));
  const name = `USE3b ${Date.now()} ${Math.random()}`;
  const created = await request.post(`${API}/api/projects`, { data: { name, latitude_deg: -6.2, longitude_deg: 106.8, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" } });
  const id: string = (await created.json()).bundle.project.project_id;
  const url = `${API}/api/projects/${id}`;
  const roof = await request.post(url + "/surfaces/rectangle", { data: { name: "USE3b roof", width_m: 1 + 20 * 1.154 - 0.01, height_m: 3.45, base_elevation_m: 6.1 } });
  const sid = (await roof.json()).bundle.scene.surfaces[0].surface_id;
  expect((await request.post(url + "/pv-fields", { data: { name: "USE3b array", support_surface_id: sid, module_definition_revision_id: "mod-rawibumi-uat-550-r1", tilt_deg: 10, row_pitch_m: 3.2, perimeter_setback_m: 0.5 } })).ok()).toBe(true);
  const inverter = await request.post(url + "/inverters", { data: { name: "INV", inverter_definition_revision_id: "inv-rawibumi-uat-150k-r1" } });
  const iid = (await inverter.json()).bundle.electrical_design.inverter_instances[0].inverter_instance_id;
  // Two strings of 9 from the first 18 modules; the last two stay unstrung.
  const modules: string[] = (await (await request.get(url)).json()).bundle.scene.module_instances.map((m: { module_instance_id: string }) => m.module_instance_id);
  const command = (n: number, ids: string[]) => ({ schema_name: "ElectricalTopologyCommand", schema_version: "0.1", command_id: `use3b-${n}-${Date.now()}`,
    command_type: "create_string", parameters: { string_id: `S00${n}`, module_instance_ids: ids } });
  expect((await request.post(url + "/electrical/commands", { data: { commands: [command(1, modules.slice(0, 9)), command(2, modules.slice(9, 18))] } })).ok()).toBe(true);
  expect((await request.post(url + "/assignments", { data: { inverter_instance_id: iid, string_ids: ["S001", "S002"] } })).ok()).toBe(true);
  const bundle = (await (await request.get(url)).json()).bundle;
  const strung = new Set(bundle.electrical_design.strings.flatMap((s: { module_instance_ids: string[] }) => s.module_instance_ids));
  const free: string[] = bundle.scene.module_instances.map((m: { module_instance_id: string }) => m.module_instance_id).filter((m: string) => !strung.has(m));
  expect(free.length).toBe(2);
  const first = bundle.electrical_design.strings[0];

  await page.addInitScript(() => window.localStorage.setItem("rawibumi.language", "en"));
  await page.goto("/"); await page.locator(".start__row", { hasText: name }).click(); await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+6");
  await page.evaluate(async (selection) => {
    const { uiStore } = await import("/src/state/store.tsx");
    uiStore.getState().dispatch({ type: "select", ids: selection });
  }, free);
  const spot = bundle.scene.module_instances.find((m: { module_instance_id: string }) => m.module_instance_id === free[0]).transform;
  await page.waitForTimeout(400); // let the plan fit before reading its view
  await page.mouse.click(...await at(page, [spot.position_x_m, spot.position_y_m]), { button: "right" });
  const committed = page.waitForResponse((r) => r.url().endsWith(`/projects/${id}/electrical/commands`) && r.request().method() === "POST");
  await page.getByRole("menuitem", { name: new RegExp(`^Add 2 to ${first.string_id} `) }).click();
  const body = (await committed).request().postDataJSON();
  expect(body.commands.map((cmd: { command_type: string }) => cmd.command_type)).toEqual(["create_string", "join_strings"]);
  const after = (await (await request.get(url)).json()).bundle.electrical_design.strings;
  expect(after.find((s: { string_id: string }) => s.string_id === first.string_id).module_instance_ids).toEqual([...first.module_instance_ids, ...free]);

  await page.keyboard.press("Alt+4");
  const panel = page.locator(".taskpanel");
  await panel.getByRole("button", { name: "Re-fill", exact: true }).click();
  await expect(panel).toContainText("Re-fill re-packs the field on its current roof");
  const preview = page.waitForResponse((r) => r.url().includes(`/projects/${id}/pv-fields/`) && r.request().method() === "PATCH" && r.request().postDataJSON().dry_run === true);
  await panel.getByRole("button", { name: "Apply re-fill", exact: true }).click();
  expect((await preview).status()).toBe(200);
  const dialog = page.getByRole("alertdialog", { name: "Preview re-fill", exact: true });
  await expect(dialog).toContainText("Modules: 20");
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  expect(errors).toEqual([]);
});
