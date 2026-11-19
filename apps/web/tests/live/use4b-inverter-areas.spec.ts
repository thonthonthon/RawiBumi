import { expect, test } from "@playwright/test";
import { openSection } from "../e2e/sections";

const API = process.env.RAWIBUMI_API;
if (!API || !/^http:\/\/127\.0\.0\.1:\d+$/.test(API) || API.endsWith(":8000"))
  throw new Error("USE4B requires a disposable API on a checked free port, never 8000.");

test("Systems assigns two roof orientations to separate MPPT sources", async ({page, request}) => {
  const name = `USE4B ${Date.now()} ${Math.random()}`;
  const created = await request.post(`${API}/api/projects`, {data: {name, latitude_deg: -6.2, longitude_deg: 106.8, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane"}});
  expect(created.ok()).toBe(true);
  const id: string = (await created.json()).bundle.project.project_id, url = `${API}/api/projects/${id}`;
  try {
    const fields: string[] = [];
    for (const [i, tilt] of [10, 25].entries()) {
      const roof = await request.post(url + "/surfaces/rectangle", {data: {name: `Roof ${i + 1}`, origin_x_m: i * 40, width_m: 16, height_m: 8, base_elevation_m: 6}});
      expect(roof.ok()).toBe(true);
      const surface = (await roof.json()).bundle.scene.surfaces[i].surface_id;
      const pv = await request.post(url + "/pv-fields", {data: {name: `PV ${i + 1}`, support_surface_id: surface, module_definition_revision_id: "mod-rawibumi-uat-550-r1", tilt_deg: tilt, row_pitch_m: 3.2}});
      expect(pv.ok()).toBe(true); fields.push((await pv.json()).bundle.scene.pv_fields[i].pv_field_id);
    }
    const added = await request.post(url + "/inverters", {data: {name: "Area inverter", inverter_definition_revision_id: "inv-rawibumi-uat-150k-r1"}});
    expect(added.ok()).toBe(true);
    const inv: string = (await added.json()).bundle.electrical_design.inverter_instances[0].inverter_instance_id;
    const sizingResponse = await request.get(url + `/inverters/${inv}/sizing`); expect(sizingResponse.ok()).toBe(true);
    const sizing = await sizingResponse.json(); expect(sizing.mppt_count).toBe(2);
    const length: number = sizing.string_length_min; expect(length).toBeGreaterThan(0); expect(length).toBeLessThanOrEqual(sizing.string_length_max);
    await page.addInitScript(() => window.localStorage.setItem("rawibumi.language", "en"));
    await page.goto("/"); await page.locator(".start__row", {hasText: name}).click();
    await expect(page.locator(".rail")).toBeVisible(); await page.keyboard.press("Alt+5");
    await openSection(page, "Inverters");
    const card = page.locator(`[data-systems-inverter="${inv}"]`); await expect(card).toBeVisible();
    await expect(card.getByLabel("Roof 2")).toBeChecked();
    await card.getByLabel("Roof 2").uncheck();
    const single = page.waitForResponse(r => r.url().endsWith(`/projects/${id}/electrical/commands`) && r.request().method() === "POST" && r.request().postDataJSON().commands.some((c: {command_type: string}) => c.command_type === "set_inverter_pairing"));
    await card.getByRole("button", {name: "Save area", exact: true}).click(); expect((await single).ok()).toBe(true);
    await expect(card).toContainText(`${(sizing.area_kwp / 2).toFixed(2)} kWp`);
    await expect(card.getByLabel("Roof 2")).not.toBeChecked();
    await card.getByLabel("Roof 2").check();
    const both = page.waitForResponse(r => r.url().endsWith(`/projects/${id}/electrical/commands`) && r.request().method() === "POST" && r.request().postDataJSON().commands.some((c: {command_type: string}) => c.command_type === "set_inverter_pairing"));
    await card.getByRole("button", {name: "Save area", exact: true}).click(); expect((await both).ok()).toBe(true);
    await expect(card).toContainText(`${sizing.area_kwp.toFixed(2)} kWp`);
    await expect(card.getByLabel("Roof 1")).toBeChecked(); await expect(card.getByLabel("Roof 2")).toBeChecked();
    await card.getByLabel("MPPT 1 source").selectOption({label: "10.0° / 0.0°"});
    await card.getByLabel("MPPT 2 source").selectOption({label: "25.0° / 0.0°"});
    for (const index of [1, 2]) {
      await card.getByLabel(`MPPT ${index} strings`).fill("1");
      await card.getByLabel(`MPPT ${index} string length`).fill(String(length));
    }
    const applied = page.waitForResponse(r => r.url().endsWith(`/projects/${id}/electrical/commands`) && r.request().method() === "POST" && !r.request().postDataJSON().dry_run && r.request().postDataJSON().commands.some((c: {command_type: string}) => c.command_type === "apply_mppt_layout"));
    await card.getByRole("button", {name: "Apply MPPT layout", exact: true}).click();
    const response = await applied; expect(response.ok()).toBe(true);
    const bundle = (await response.json()).bundle;
    expect(bundle.electrical_design.inverter_instances[0].paired_pv_field_ids).toEqual(fields);
    const modules = new Map<string, string>(bundle.scene.module_instances.map((m: {module_instance_id: string; pv_field_id: string}) => [m.module_instance_id, m.pv_field_id]));
    const mppts = bundle.electrical_design.mppt_instances.sort((a: {index: number}, b: {index: number}) => a.index - b.index);
    const used: string[] = [];
    for (const [i, mppt] of mppts.entries()) {
      const strings = bundle.electrical_design.strings.filter((s: {target_mppt_instance_id: string}) => s.target_mppt_instance_id === mppt.mppt_instance_id);
      expect(strings).toHaveLength(1); expect(strings[0].module_instance_ids).toHaveLength(length);
      expect(strings[0].module_instance_ids.every((mid: string) => modules.get(mid) === fields[i])).toBe(true);
      used.push(...strings[0].module_instance_ids);
    }
    expect(new Set(used).size).toBe(used.length);
    await card.getByLabel("MPPT 2 source").selectOption("");
    await expect(card.locator("[data-mixed-orientation]")).toContainText("RawiBumi simulates it physically");
  } finally { expect((await request.delete(url, {params: {confirm: id}})).ok()).toBe(true); }
});
