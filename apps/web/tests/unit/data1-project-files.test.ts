import { afterEach, expect, it, vi } from "vitest";
import { api } from "../../src/api";
import { mockApi } from "../../src/demo/mockApi";
import { DemoUnavailableError } from "../../src/engine/adapter";
import { ApiError } from "../../src/types";

afterEach(() => { vi.unstubAllGlobals(); });

it("export downloads the archive with the server's filename and the results choice", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(new Blob([new Uint8Array([80, 75, 3, 4])]), { status: 200, headers: { "Content-Disposition": 'attachment; filename="Roof_A-project-1.rawibumi"' } }));
  vi.stubGlobal("fetch", fetch);
  const file = await api.exportProject("project-1", false);
  expect(fetch.mock.calls[0][0]).toBe("/api/projects/project-1/export?include_results=false");
  expect(file.filename).toBe("Roof_A-project-1.rawibumi");
  expect(new Uint8Array(await file.blob.arrayBuffer())).toEqual(new Uint8Array([80, 75, 3, 4]));
});

it("an export refusal keeps the engine's code, so the browser can offer a backup restore", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: { code: "project_unreadable", message: "Project p can't be read" } }), { status: 409 })));
  const error = await api.exportProject("p", true).catch((e) => e);
  expect(error).toBeInstanceOf(ApiError);
  expect(error.status).toBe(409);
  expect(error.detail).toMatchObject({ code: "project_unreadable" });
});

it("import posts the raw file with replace only when asked; backups and restore use their routes", async () => {
  const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response("[]", { status: 200 })));
  vi.stubGlobal("fetch", fetch);
  const file = new Blob([new Uint8Array([1, 2, 3])]);
  await api.importProject(file, "my project.rawibumi");
  await api.importProject(file, "my project.rawibumi", true);
  await api.projectBackups("p 1");
  await api.restoreBackup("p", "20261108T010203000004Z-r3");
  expect(fetch.mock.calls.map((c) => [c[0], c[1]?.method ?? "GET"])).toEqual([
    ["/api/projects/import?filename=my%20project.rawibumi&replace=false", "POST"],
    ["/api/projects/import?filename=my%20project.rawibumi&replace=true", "POST"],
    ["/api/projects/p%201/backups", "GET"],
    ["/api/projects/p/backups/20261108T010203000004Z-r3/restore", "POST"]
  ]);
  expect(fetch.mock.calls[0][1].body).toBe(file);
});

it("the demo engine declines project files instead of imitating them", async () => {
  await expect(mockApi.exportProject()).rejects.toBeInstanceOf(DemoUnavailableError);
  await expect(mockApi.importProject()).rejects.toBeInstanceOf(DemoUnavailableError);
  await expect(mockApi.projectBackups()).rejects.toBeInstanceOf(DemoUnavailableError);
  await expect(mockApi.restoreBackup()).rejects.toBeInstanceOf(DemoUnavailableError);
});
