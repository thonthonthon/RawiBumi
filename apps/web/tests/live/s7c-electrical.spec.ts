import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import type { ProjectView } from "../../src/types";

type View = ProjectView & { bundle: { electrical_design: { revision_number: number; mppt_instances: Array<{ mppt_instance_id: string; connected_string_ids: string[] }> } } };
const API = process.env.RAWIBUMI_API;
if (!API || !/^http:\/\/127\.0\.0\.1:\d+$/.test(API) || API.endsWith(":8000")) throw new Error("S7c requires the isolated test launcher on a checked-free loopback port, never 8000.");
const path = (id: string) => `${API}/api/projects/${id}`;
async function view(request: APIRequestContext, id: string): Promise<View> {
  const result = await request.get(path(id)); expect(result.ok()).toBe(true); return result.json();
}
async function setup(request: APIRequestContext, suffix: string, count: number, length?: number) {
  const catalog = await (await request.get(`${API}/api/catalog`)).json();
  const module = catalog.modules.find((m: { revision_id: string }) => m.revision_id === "mod-rawibumi-uat-550-r1") ?? catalog.modules[0];
  const inverter = catalog.inverters.find((i: { revision_id: string }) => i.revision_id === "inv-rawibumi-uat-150k-r1"); expect(inverter).toBeTruthy();
  const name = `S7c ${suffix} ${Date.now()}`;
  const project = await request.post(`${API}/api/projects`, { data: { name, latitude_deg: -6.2, longitude_deg: 106.8, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" } }); expect(project.ok()).toBe(true);
  const id: string = (await project.json()).bundle.project.project_id;
  const roof = await request.post(path(id) + "/surfaces/rectangle", { data: { name: "Electrical roof", width_m: 1 + count * (module.width_m + 0.02) - 0.01, height_m: 1 + module.height_m * Math.cos(Math.PI / 18) + 0.05, base_elevation_m: 0 } }); expect(roof.ok()).toBe(true);
  const surface = (await roof.json()).bundle.scene.surfaces[0].surface_id;
  const field = await request.post(path(id) + "/pv-fields", { data: { name: "Electrical field", support_surface_id: surface, module_definition_revision_id: module.revision_id, tilt_deg: 10, row_pitch_m: 3.2, module_gap_x_m: 0.02, perimeter_setback_m: 0.5, obstacle_setback_m: 0.3 } }); expect(field.ok()).toBe(true);
  expect((await field.json()).bundle.scene.module_instances).toHaveLength(count);
  expect((await request.post(path(id) + "/inverters", { data: { inverter_definition_revision_id: inverter.revision_id, name: "INV-01" } })).ok()).toBe(true);
  if (length) expect((await request.post(path(id) + "/strings", { data: { string_length: length, allow_shorter_remainder: false } })).ok()).toBe(true);
  return { id, name, initial: await view(request, id) };
}
async function open(page: Page, name: string) {
  await page.goto("/"); await page.locator(".start__row", { hasText: name }).click(); await expect(page.locator(".rail")).toBeVisible(); await page.keyboard.press("Alt+6");
  await expect(page.getByRole("treegrid", { name: /Electrical topology/ })).toBeVisible();
}
function centre(v: View, moduleId: string): [number, number] {
  const polygon = v.scene_view.local_features.find((f) => f.id === moduleId)!.polygon;
  return [polygon.reduce((sum, p) => sum + p[0], 0) / polygon.length, polygon.reduce((sum, p) => sum + p[1], 0) / polygon.length];
}
async function point(page: Page, v: View, x: number, y: number): Promise<[number, number]> {
  const points = v.scene_view.local_features.flatMap((f) => f.polygon);
  const minX = Math.min(...points.map((p) => p[0])), maxX = Math.max(...points.map((p) => p[0]));
  const minY = Math.min(...points.map((p) => p[1])), maxY = Math.max(...points.map((p) => p[1]));
  // No pan or zoom in these fixtures. Wait for the initial fitted viewport, then use its rendered scale.
  await page.waitForFunction(({ minX, maxX, minY, maxY }) => {
    const canvas = document.querySelector<HTMLCanvasElement>(".plan__canvas"), bar = document.querySelector<HTMLElement>(".plan__scalebar");
    if (!canvas || !bar) return false;
    const scale = parseFloat(bar.style.width) / parseFloat(bar.parentElement!.querySelector("span")!.textContent!);
    const expected = Math.max(0.02, Math.min(400, (canvas.clientWidth - 120) / Math.max(maxX - minX, 4), (canvas.clientHeight - 120) / Math.max(maxY - minY, 4)));
    return Math.abs(scale - expected) < 1e-4;
  }, { minX, maxX, minY, maxY });
  return page.evaluate(({ x, y, cx, cy }) => {
    const canvas = document.querySelector<HTMLCanvasElement>(".plan__canvas")!, box = canvas.getBoundingClientRect();
    const bar = document.querySelector<HTMLElement>(".plan__scalebar")!;
    const scale = parseFloat(bar.style.width) / parseFloat(bar.parentElement!.querySelector("span")!.textContent!);
    return [box.left + canvas.clientWidth / 2 + (x - cx) * scale, box.top + canvas.clientHeight / 2 - (y - cy) * scale];
  }, { x, y, cx: (minX + maxX) / 2, cy: (minY + maxY) / 2 });
}
async function clickModule(page: Page, v: View, id: string) { await page.mouse.click(...await point(page, v, ...centre(v, id))); }
async function lasso(page: Page, v: View, ids: string[]) {
  const centres = ids.map((id) => centre(v, id));
  const minX = Math.min(...centres.map((p) => p[0])) - 0.2, maxX = Math.max(...centres.map((p) => p[0])) + 0.2;
  const minY = Math.min(...centres.map((p) => p[1])) - 0.9, maxY = Math.max(...centres.map((p) => p[1])) + 0.9;
  await page.keyboard.press("l"); const start = await point(page, v, minX, minY);
  await page.mouse.move(...start); await page.mouse.down();
  for (const [x, y] of [[maxX, minY], [maxX, maxY], [minX, maxY], [minX, minY]]) await page.mouse.move(...await point(page, v, x, y), { steps: 5 });
  await page.mouse.up();
  await expect(page.locator(".taskpanel")).toContainText(`${ids.length} modules selected`);
}

test("audit: capacity refusal, assign 3 + 3 through lasso and targets, delete the seventh", async ({ page, request }) => {
  const { id, name, initial } = await setup(request, "audit", 140, 20); await open(page, name);
  const strings = initial.bundle.electrical_design.strings; expect(strings).toHaveLength(7);
  const mppts = initial.bundle.electrical_design.inverter_instances[0].mppt_instance_ids;
  await lasso(page, initial, strings.slice(0, 4).flatMap((s) => s.module_instance_ids)); await page.keyboard.press("1");
  const refusal = page.waitForResponse((r) => r.url().endsWith("/electrical/commands") && r.request().method() === "POST");
  await page.locator(".taskpanel").getByRole("button", { name: "Assign strings to target", exact: true }).click();
  const refused = await refusal; expect(refused.status()).toBe(422); const message = (await refused.json()).detail;
  expect(message).toContain("verified DC inputs"); await expect(page.locator(".toasts")).toContainText(message); expect(await view(request, id)).toEqual(initial);
  for (const [index, chosen] of [strings.slice(0, 3), strings.slice(3, 6)].entries()) {
    await lasso(page, initial, chosen.flatMap((s) => s.module_instance_ids)); await page.keyboard.press(String(index + 1));
    await page.locator(".taskpanel").getByRole("button", { name: "Assign strings to target", exact: true }).click();
    await expect.poll(async () => (await view(request, id)).bundle.electrical_design.strings.filter((s) => s.target_mppt_instance_id === mppts[index]).map((s) => s.string_id)).toEqual(chosen.map((s) => s.string_id));
  }
  await page.getByRole("button", { name: `Select string ${strings[6].string_id}`, exact: true }).click();
  await page.locator(".taskpanel").getByRole("button", { name: "Delete strings", exact: true }).click();
  await expect.poll(async () => (await view(request, id)).bundle.electrical_design.strings.length).toBe(6);
  const final = await view(request, id);
  expect(final.bundle.electrical_design.strings.map((s) => s.string_id)).toEqual(strings.slice(0, 6).map((s) => s.string_id));
  expect(final.bundle.electrical_design.mppt_instances.map((m) => m.connected_string_ids)).toEqual([strings.slice(0, 3).map((s) => s.string_id), strings.slice(3, 6).map((s) => s.string_id)]);
  const ready = await (await request.get(path(id) + "/execution-readiness")).json();
  expect(ready.findings.filter((f: { severity: string; category: string }) => ["blocking", "blocking_error", "error"].includes(f.severity) && f.category === "design_validation")).toEqual([]);
});

test("string paths preserve click order, create-and-assign atomically, then string a lasso selection", async ({ page, request }) => {
  const { id, name, initial } = await setup(request, "paths", 12); await open(page, name);
  const modules = initial.bundle.scene.module_instances.map((m) => m.module_instance_id), mppt = initial.bundle.electrical_design.inverter_instances[0].mppt_instance_ids[0];
  const paths = [[modules[2], modules[0], modules[1]], [modules[5], modules[3], modules[4]]];
  const posts: Record<string, unknown>[] = []; page.on("request", (r) => { if (r.method() === "POST" && r.url().endsWith("/electrical/commands")) posts.push(r.postDataJSON()); });
  for (const [index, ids] of paths.entries()) {
    if (index) await page.keyboard.press("1");
    const before = await view(request, id);
    await page.keyboard.press("s"); for (const moduleId of ids) await clickModule(page, initial, moduleId); await page.keyboard.press("Enter");
    await expect.poll(async () => (await view(request, id)).bundle.electrical_design.strings.length).toBe(index + 1);
    const after = await view(request, id), string = after.bundle.electrical_design.strings.at(-1)!;
    expect(string.module_instance_ids).toEqual(ids); expect(string.target_mppt_instance_id).toBe(index ? mppt : null);
    expect(after.bundle.electrical_design.revision_number).toBe(before.bundle.electrical_design.revision_number + 1);
    expect(posts).toHaveLength(index + 1);
    const commands = posts[index].commands as Array<{ command_type: string; parameters: { string_id?: string; string_ids?: string[] } }>;
    expect(commands.map((c) => c.command_type)).toEqual(index ? ["create_string", "assign_strings_to_mppt"] : ["create_string"]);
    expect(commands[0].parameters.string_id).toBe(`S00${index + 1}`);
    if (index) expect(commands[1].parameters.string_ids).toEqual([string.string_id]);
    await expect(page.getByRole("button", { name: `Select string ${string.string_id}`, exact: true })).toBeVisible();
  }
  const count = posts.length;
  await clickModule(page, initial, modules[0]); await page.keyboard.press("Enter");
  await expect(page.locator(".toasts")).toContainText("S001"); expect(posts).toHaveLength(count);
  await lasso(page, initial, modules.slice(6));
  await page.locator(".taskpanel").getByRole("button", { name: "Rules", exact: true }).click();
  await page.locator(".taskpanel").getByLabel("Modules per string").fill("3");
  await page.locator(".taskpanel").getByRole("button", { name: /String the selection/ }).click();
  await expect.poll(async () => (await view(request, id)).bundle.electrical_design.strings.length).toBe(4);
  expect(posts).toHaveLength(count + 1);
  const batch = posts.at(-1)!.commands as Array<{ command_type: string; parameters: { module_instance_ids: string[]; ordering: string; remainder_policy: string } }>;
  expect(batch).toHaveLength(1); expect(batch[0].command_type).toBe("create_strings");
  expect(batch[0].parameters).toMatchObject({ module_instance_ids: modules.slice(6), ordering: "row_major", remainder_policy: "error" });
});

test("S14a tools and serpentine carry no pending badge, and choosing them sends no electrical request", async ({ page, request }) => {
  const { name } = await setup(request, "pending", 40, 20); await open(page, name);
  const toolbar = page.getByRole("toolbar", { name: "Electrical tools", exact: true });
  for (const name of ["String path", "Assign", "Split", "Join", "Reverse", "Move module", "Swap modules"]) await expect(toolbar.getByRole("button", { name: new RegExp(`^${name}`) }).locator(".notwired")).toHaveCount(0);
  const requests: string[] = []; page.on("request", (r) => { if (r.method() === "POST" && /\/(electrical\/commands|assignments|strings)$/.test(r.url())) requests.push(r.url()); });
  await page.locator(".taskpanel").getByRole("button", { name: "Rules", exact: true }).click();
  await page.getByRole("radio", { name: "Serpentine", exact: true }).click();
  await expect(page.locator('.taskpanel .notwired[title*="serpentine"]')).toHaveCount(0);
  expect(requests).toEqual([]);
});

test("Delete strings waits for the previous command's saved but unsettled response", async ({ page, request }) => {
  const { id, name, initial } = await setup(request, "settling response", 40, 20); await open(page, name);
  const [first, second] = initial.bundle.electrical_design.strings;
  let markSaved!: () => void, release!: () => void;
  const saved = new Promise<void>((resolve) => { markSaved = resolve; });
  const held = new Promise<void>((resolve) => { release = resolve; });
  const posts: string[] = [];
  page.on("request", (r) => { if (r.method() === "POST" && r.url().endsWith("/electrical/commands")) posts.push(r.postDataJSON().commands[0].command_type); });
  await page.route("**/electrical/commands", async (route) => {
    if (route.request().postDataJSON().commands[0].command_type !== "assign_strings_to_mppt") return route.continue();
    const response = await route.fetch(); expect(response.ok()).toBe(true);
    markSaved(); await held; await route.fulfill({ response });
  });
  try {
    await page.getByRole("button", { name: `Select string ${first.string_id}`, exact: true }).click();
    await page.keyboard.press("1");
    await page.locator(".taskpanel").getByRole("button", { name: "Assign strings to target", exact: true }).click();
    await saved;
    const persisted = await view(request, id);
    expect(persisted.bundle.electrical_design.strings.find((s) => s.string_id === first.string_id)!.target_mppt_instance_id).toBe(initial.bundle.electrical_design.inverter_instances[0].mppt_instance_ids[0]);
    await page.getByRole("button", { name: `Select string ${second.string_id}`, exact: true }).click();
    const deletion = page.locator(".taskpanel").getByRole("button", { name: "Delete strings", exact: true });
    await expect(deletion).toBeDisabled();
    await expect(page.locator(".taskpanel").getByRole("button", { name: "Unassign", exact: true })).toBeDisabled();
    await expect(page.locator(".taskpanel").getByRole("button", { name: "Add inverter", exact: true })).toBeDisabled();
    const click = deletion.click(); // Playwright must wait until the response settles and the button enables.
    await expect(deletion).toBeDisabled(); expect(posts).toEqual(["assign_strings_to_mppt"]);
    expect((await view(request, id)).bundle.electrical_design.strings).toHaveLength(2);
    release(); await click;
    await expect.poll(async () => (await view(request, id)).bundle.electrical_design.strings.map((s) => s.string_id)).toEqual([first.string_id]);
    expect(posts).toEqual(["assign_strings_to_mppt", "delete_string"]);
  } finally {
    release();
    await page.unroute("**/electrical/commands");
  }
});
