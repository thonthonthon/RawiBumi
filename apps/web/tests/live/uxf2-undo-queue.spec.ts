import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { edgeNormal, offsetEdge } from "../../src/canvas/plan/edit";
import type { Vec2 } from "../../src/geometry";
import type { ProjectView, ObstacleConflictDetail } from "../../src/types";

const API = process.env.RAWIBUMI_API;
if (!API || !/^http:\/\/127\.0\.0\.1:\d+$/.test(API) || API.endsWith(":8000")) throw new Error("UXF2 requires a checked-free test-only API, never a user store or port 8000.");
const url = (id: string) => `${API}/api/projects/${id}`;
async function get(request: APIRequestContext, id: string): Promise<ProjectView> {
  const response = await request.get(url(id)); expect(response.ok()).toBe(true); return response.json();
}
async function create(request: APIRequestContext, suffix: string, withField = false) {
  const name = `S11a ${suffix} ${Date.now()}`;
  const response = await request.post(`${API}/api/projects`, { data: { name, latitude_deg: -6.2, longitude_deg: 106.8, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" } });
  expect(response.ok()).toBe(true); const id = (await response.json()).bundle.project.project_id as string;
  const roof = await request.post(url(id)+"/surfaces/rectangle", { data: { name: "S11a roof", width_m: 20, height_m: 10, base_elevation_m: 6.1 } });
  expect(roof.ok()).toBe(true); const sid = (await roof.json()).bundle.scene.surfaces[0].surface_id as string;
  if (withField) {
    const catalog = await (await request.get(`${API}/api/catalog`)).json();
    const module = catalog.modules.find((m: { revision_id: string }) => m.revision_id==="mod-rawibumi-uat-550-r1") ?? catalog.modules[0];
    expect((await request.post(url(id)+"/pv-fields", { data: { name:"S11a field", support_surface_id:sid, module_definition_revision_id:module.revision_id, tilt_deg:10, row_pitch_m:3.1, perimeter_setback_m:.5, obstacle_setback_m:.3 } })).ok()).toBe(true);
  }
  return {id,name,sid};
}
async function open(page: Page, name: string) {
  await page.goto("/"); await page.locator(".start__row", {hasText:name}).click();
  await expect(page.locator(".rail")).toBeVisible(); await page.keyboard.press("Alt+3"); await expect(page.locator(".toollist")).toBeVisible();
}
async function typed(page: Page, value: string) {
  await page.keyboard.type(value); await expect(page.locator(".plan__typed")).toBeVisible(); await page.keyboard.press("Enter");
  await expect(page.locator(".plan__typed")).toBeHidden();
}
async function point(page: Page, x: number, y: number): Promise<[number, number]> {
  // Each project starts on its only 20 x 10 roof; no test pans or zooms.
  return page.evaluate(([x,y]) => {
    const canvas=document.querySelector<HTMLCanvasElement>(".plan__canvas")!, box=canvas.getBoundingClientRect();
    const bar=document.querySelector<HTMLElement>(".plan__scalebar")!;
    const scale=parseFloat(bar.style.width)/parseFloat(bar.parentElement!.querySelector("span")!.textContent!);
    return [box.left+canvas.clientWidth/2+(x-10)*scale,box.top+canvas.clientHeight/2-(y-5)*scale];
  },[x,y]);
}

// UXF2 (U2-22): Ctrl+Z pressed while a PV-roof edit is still saving (the field re-fills) is queued, not lost.
test("undo pressed while a PV roof vertex drag is saving runs when the save finishes", async ({ page, request }) => {
  const { id, name, sid } = await create(request, "uxf2-undo", true);
  await open(page, name);
  await page.locator(".taskpanel .layer__name", { hasText: "S11a roof" }).click();
  const ring = async () => (await get(request, id)).scene_view.local_features.find((f) => f.id === sid)!.polygon;
  const before = JSON.stringify(await ring()); const pastBefore = await page.evaluate(async () => (await import("/src/state/store.tsx")).uiStore.getState().state.past.length);
  await page.mouse.move(...await point(page, 20, 10)); await page.mouse.down();
  await page.mouse.move(...await point(page, 21, 11), { steps: 6 }); await page.mouse.up();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: /Confirm/ }).click();
  const busy = () => page.evaluate(async () => (await import("/src/state/store.tsx")).uiStore.getState().state.busy);
  await expect.poll(busy).not.toBeNull();
  await page.keyboard.press("Control+z"); // while the roof and its field are still saving
  await expect(page.locator(".toasts")).toContainText("Undo will run when saving finishes.");
  await expect.poll(async () => JSON.stringify(await ring()), { timeout: 30_000 }).toBe(before);
  await expect.poll(busy).toBeNull();
  expect(await page.evaluate(async () => (await import("/src/state/store.tsx")).uiStore.getState().state.past.length)).toBe(pastBefore);
});
