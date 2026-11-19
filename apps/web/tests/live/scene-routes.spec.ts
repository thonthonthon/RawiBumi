import { expect, test, type APIRequestContext } from "@playwright/test";

// F3 gate: "existing scene routes work live". The plan tools call the engine's
// own routes (surfaces/rectangle, obstacles/box, scene/move) through the HTTP
// adapter, and the engine's answer is what the plan then shows.

const API = process.env.RAWIBUMI_API ?? "http://127.0.0.1:8000";

interface Feature {
  id: string;
  category: string;
  name: string;
  polygon: [number, number][];
}
interface View {
  bundle: { project: { project_id: string } };
  scene_view: { local_features: Feature[] };
}

async function project(api: APIRequestContext, id: string): Promise<View> {
  const r = await api.get(`${API}/api/projects/${id}`);
  expect(r.ok()).toBe(true);
  return (await r.json()) as View;
}

test("rectangle roof, box obstacle and move go through the engine's routes", async ({ page, request }) => {
  const health = await request.get(`${API}/api/health`).catch(() => null);
  test.skip(!health?.ok(), `Engine API not reachable at ${API}`);

  const created = await request.post(`${API}/api/projects`, {
    data: { name: `F3 live ${Date.now()}`, latitude_deg: -6.9, longitude_deg: 107.6, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" }
  });
  expect(created.ok()).toBe(true);
  const id = ((await created.json()) as View).bundle.project.project_id;

  await page.goto("/");
  await page.getByText(/F3 live/).first().click();
  await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+3");
  await expect(page.locator('.rail [aria-current="step"]')).toContainText("Scene");
  await expect(page.locator(".taskpanel .toollist")).toBeVisible();

  // B: two typed corners → POST surfaces/rectangle.
  await page.keyboard.press("b");
  await expect(page.locator('.taskpanel button[aria-pressed="true"]', { hasText: "Rectangle roof" })).toBeVisible();
  for (const s of ["0,0", "@12,8"]) {
    await page.keyboard.type(s);
    await page.keyboard.press("Enter");
  }
  await expect(page.locator(".toasts")).toContainText("Roof created in the engine.");
  let v = await project(request, id);
  const roof = v.scene_view.local_features.find((f) => f.category === "surface");
  expect(roof).toBeTruthy();
  const xs = roof!.polygon.map((p) => p[0]);
  const ys = roof!.polygon.map((p) => p[1]);
  expect(Math.max(...xs) - Math.min(...xs)).toBeCloseTo(12, 6);
  expect(Math.max(...ys) - Math.min(...ys)).toBeCloseTo(8, 6);

  // O: two typed corners → POST obstacles/box with the panel's height.
  await page.keyboard.press("o");
  for (const s of ["2,2", "@1.5,1"]) {
    await page.keyboard.type(s);
    await page.keyboard.press("Enter");
  }
  await expect(page.locator(".toasts")).toContainText("Obstacle created in the engine.");
  v = await project(request, id);
  const box = v.scene_view.local_features.find((f) => f.category !== "surface" && f.category !== "module");
  expect(box).toBeTruthy();

  // M on the engine roof: typed base and @dx,dy → POST scene/move; the engine's new vertices come back.
  await page.locator(".taskpanel .layer__name", { hasText: roof!.name }).click();
  await page.keyboard.press("m");
  for (const s of ["0,0", "@3,-2"]) {
    await page.keyboard.type(s);
    await page.keyboard.press("Enter");
  }
  await expect.poll(async () => {
    const after = (await project(request, id)).scene_view.local_features.find((f) => f.id === roof!.id)!;
    return Math.min(...after.polygon.map((p) => p[0]));
  }).toBeCloseTo(Math.min(...xs) + 3, 6);
  const moved = (await project(request, id)).scene_view.local_features.find((f) => f.id === roof!.id)!;
  expect(Math.min(...moved.polygon.map((p) => p[1]))).toBeCloseTo(Math.min(...ys) - 2, 6);
  // The plan shows the engine's geometry, not a local draft.
  await expect(page.locator(".inspectorpane")).not.toContainText("local draft");
});

// F4: until the table-level fill route exists (proposal 0003), a fill the engine's
// current PV field route can express goes there; the preview reports the route missing.
test("a one-row-per-table fill goes through the engine's current PV field route", async ({ page, request }) => {
  const health = await request.get(`${API}/api/health`).catch(() => null);
  test.skip(!health?.ok(), `Engine API not reachable at ${API}`);

  const created = await request.post(`${API}/api/projects`, {
    data: { name: `F4 live ${Date.now()}`, latitude_deg: -6.9, longitude_deg: 107.6, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" }
  });
  const id = ((await created.json()) as View).bundle.project.project_id;
  await page.goto("/");
  await page.getByText(/F4 live/).first().click();
  await page.keyboard.press("Alt+3");
  await expect(page.locator('.rail [aria-current="step"]')).toContainText("Scene");
  await expect(page.locator(".taskpanel .toollist")).toBeVisible();
  await page.keyboard.press("b");
  await expect(page.locator('.taskpanel button[aria-pressed="true"]', { hasText: "Rectangle roof" })).toBeVisible();
  for (const s of ["0,0", "@20,10"]) {
    await page.keyboard.type(s);
    await page.keyboard.press("Enter");
  }
  await expect(page.locator(".toasts")).toContainText("Roof created in the engine.");
  await page.keyboard.press("Alt+4");
  const p = page.locator(".taskpanel");
  await p.getByLabel("Field name").fill("Live tilt 15");
  await p.getByLabel("Tilt").fill("15");
  await p.getByLabel("Aisle").fill("0.8");
  await expect(p.locator(".preview-box")).toContainText("The fill preview needs the engine's table-level fill route.");
  await expect(p.locator(".preview-box")).toContainText("Apply fills through it");
  await p.getByRole("button", { name: "Apply fill" }).click();
  await expect(page.locator(".toasts")).toContainText("PV field filled by the engine.");

  const v = (await (await request.get(`${API}/api/projects/${id}`)).json()) as {
    bundle: { scene: { pv_fields: Array<{ name: string; tilt_deg: number; row_pitch_m?: number }>; module_instances: unknown[] } };
  };
  expect(v.bundle.scene.pv_fields).toHaveLength(1);
  expect(v.bundle.scene.pv_fields[0].name).toBe("Live tilt 15");
  expect(v.bundle.scene.pv_fields[0].tilt_deg).toBe(15);
  expect(v.bundle.scene.module_instances.length).toBeGreaterThan(0);

  // Undo the fill: the previous roof had no field or modules.
  const undone = page.waitForResponse((r) => r.url().endsWith(`/api/projects/${id}/undo`) && r.request().method() === "POST");
  await page.keyboard.press("Control+z");
  expect((await undone).ok()).toBe(true);
  await expect.poll(async () => {
    const previous = await (await request.get(`${API}/api/projects/${id}`)).json();
    return { fields: previous.bundle.scene.pv_fields.length, modules: previous.bundle.scene.module_instances.length };
  }).toEqual({ fields: 0, modules: 0 });
});
