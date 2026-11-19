import { afterEach, describe, expect, it, vi } from "vitest";
import { exportAPI, type CSVExportRequest } from "../../src/api";

const input: CSVExportRequest = { format: "csv", resolution: "hourly", level: "project", columns: ["pcc_power_w"] };

afterEach(() => vi.unstubAllGlobals());

describe("numerical CSV export API", () => {
  it("returns the binary ZIP unchanged and sends the selected IDs and approved options", async () => {
    const bytes = new Uint8Array([80, 75, 3, 4, 0, 255, 128, 10]);
    const fetcher = vi.fn().mockResolvedValue(new Response(bytes, { headers: { "Content-Type": "application/zip" } }));
    vi.stubGlobal("fetch", fetcher);
    const blob = await exportAPI.exportCSV("project space", "run#1", input);
    expect(blob.type).toBe("application/zip");
    expect(new Uint8Array(await blob.arrayBuffer())).toEqual(bytes);
    expect(fetcher).toHaveBeenCalledWith("/api/projects/project%20space/runs/run%231/exports", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input)
    });
  });

  it("fetches the selected run schema and preserves source IDs and units", async () => {
    const schema = { project_id: "p", run_id: "r", row_count: 3, columns: [{ id: "pcc_power_w", unit: "W" }] };
    const fetcher = vi.fn().mockResolvedValue(Response.json(schema));
    vi.stubGlobal("fetch", fetcher);
    expect(await exportAPI.exportSchema("p", "r")).toEqual(schema);
    expect(fetcher.mock.calls[0][0]).toBe("/api/projects/p/runs/r/exports/schema");
  });

  it.each([
    [{ detail: "run package artifact hash mismatch: timeseries.parquet" }, "run package artifact hash mismatch: timeseries.parquet"],
    [{ detail: [{ loc: ["body", "columns", 0], msg: "Input should be a valid string" }] }, "body.columns.0: Input should be a valid string"],
  ])("keeps useful backend errors (%j)", async (payload, message) => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => Response.json(payload, { status: 422 })));
    await expect(exportAPI.exportCSV("p", "r", input)).rejects.toThrow(message);
    await expect(exportAPI.exportSchema("p", "r")).rejects.toThrow(message);
  });

  it("keeps a non-JSON proxy error useful", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>proxy failure</html>", { status: 502, statusText: "Bad Gateway" })));
    await expect(exportAPI.exportCSV("p", "r", input)).rejects.toThrow("Bad Gateway");
  });

  it("has a status-code fallback and propagates network failures", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 503 })));
    await expect(exportAPI.exportCSV("p", "r", input)).rejects.toThrow("Request failed: 503");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Connection lost")));
    await expect(exportAPI.exportCSV("p", "r", input)).rejects.toThrow("Connection lost");
  });

  it("refuses a successful HTML or JSON response presented as a download", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>login</html>", { headers: { "Content-Type": "text/html" } })));
    await expect(exportAPI.exportCSV("p", "r", input)).rejects.toThrow("application/zip");
  });
});
