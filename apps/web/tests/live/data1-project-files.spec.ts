import { expect, test, type APIRequestContext } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
const API = process.env.RAWIBUMI_API;
if (!API || !/^http:\/\/127\.0\.0\.1:\d+$/.test(API) || API.endsWith(":8000")) throw new Error("DATA1 requires the disposable test API, never var/projects.");
const ROOT = path.resolve(process.cwd(), "../..");

async function view(request: APIRequestContext, id: string) { return request.get(`${API}/api/projects/${id}`); }

test("export, delete, import, replace on clash, restore a backup, and recover an unreadable project", async ({ page, request }) => {
  test.setTimeout(180_000);
  const name = `DATA1 files ${Date.now()} ${Math.random()}`;
  const created = await request.post(`${API}/api/projects`, { data: { name, latitude_deg: -6.2, longitude_deg: 106.8, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" } });
  expect(created.ok()).toBe(true); const id: string = (await created.json()).bundle.project.project_id;
  expect((await request.post(`${API}/api/projects/${id}/surfaces/rectangle`, { data: { name: "Kept roof", width_m: 10, height_m: 6, base_elevation_m: 6 } })).ok()).toBe(true);
  const original = await (await view(request, id)).json();
  const errors: string[] = []; page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  const row = () => page.locator("tr", { has: page.locator(".start__row", { hasText: name }) });

  // Export from the project list.
  await row().getByRole("button", { name: "Export…", exact: true }).click();
  const dialog = page.locator("[data-export-project]");
  await expect(dialog.getByLabel("Include saved results")).toBeChecked();
  const downloading = page.waitForEvent("download");
  await dialog.getByRole("button", { name: "Download", exact: true }).click();
  const download = await downloading;
  expect(download.suggestedFilename()).toMatch(new RegExp(`${id}\\.rawibumi$`));
  const file = readFileSync((await download.path())!);

  // Delete, then import: the project comes back with the same ID and opens.
  expect((await request.delete(`${API}/api/projects/${id}`, { params: { confirm: id } })).ok()).toBe(true);
  await page.reload(); await expect(row()).toHaveCount(0);
  await page.locator("[data-import-project]").setInputFiles({ name: download.suggestedFilename(), mimeType: "application/zip", buffer: file });
  await expect(page.locator(".rail")).toBeVisible();
  const imported = await (await view(request, id)).json();
  expect(imported.bundle.scene).toEqual(original.bundle.scene);
  expect(imported.bundle.project.name).toBe(name);

  // Importing again asks before replacing.
  await page.getByRole("button", { name: "Projects", exact: true }).click();
  await page.locator("[data-import-project]").setInputFiles({ name: "again.rawibumi", mimeType: "application/zip", buffer: file });
  const clash = page.getByRole("alertdialog", { name: "This project already exists" });
  await expect(clash).toBeVisible();
  await clash.getByRole("button", { name: "Replace", exact: true }).click();
  await expect(page.locator(".rail")).toBeVisible();

  // A rename, then restore the backup before it.
  expect((await request.patch(`${API}/api/projects/${id}`, { data: { name: `${name} renamed` } })).ok()).toBe(true);
  await page.getByRole("button", { name: "Projects", exact: true }).click(); await page.reload();
  await page.locator("tr", { has: page.locator(".start__row", { hasText: `${name} renamed` }) }).getByRole("button", { name: "Backups…", exact: true }).click();
  const backups = page.locator("[data-backups] tbody tr");
  await expect(backups.first()).toContainText("current");
  await backups.nth(1).getByRole("button", { name: "Restore", exact: true }).click();
  await page.locator("[data-backups] [role=alert]").getByRole("button", { name: "Restore", exact: true }).click();
  await expect(page.locator(".rail")).toBeVisible();
  await expect.poll(async () => (await (await view(request, id)).json()).bundle.project.name).toBe(name);

  // Damage the file on disk: the list shows it as unreadable, and a backup brings it back.
  execFileSync(path.join(ROOT, ".venv/bin/python"), ["-c", `
import sys
from pathlib import Path
store = (Path(sys.argv[1]) / 'tmp/live-projects').resolve()
target = (store / (sys.argv[2] + '.json')).resolve()
assert target.parent == store and target.is_file()
target.write_bytes(b'{"schema_name": "ProjectWorkspaceBundle", "trunc')
`, ROOT, id], { cwd: ROOT, timeout: 30_000 });
  expect((await view(request, id)).status()).toBe(409);
  await page.getByRole("button", { name: "Projects", exact: true }).click(); await page.reload();
  const broken = page.locator(`[data-unreadable="${id}"]`);
  await expect(broken).toContainText("not valid JSON");
  await broken.getByRole("button", { name: "Restore from backup…", exact: true }).click();
  await backups.first().getByRole("button", { name: "Restore", exact: true }).click();
  await page.locator("[data-backups] [role=alert]").getByRole("button", { name: "Restore", exact: true }).click();
  await expect(page.locator(".rail")).toBeVisible();
  expect((await view(request, id)).status()).toBe(200);
  expect(errors).toEqual([]);
});
