import { describe, expect, it } from "vitest";
import { DemoUnavailableError, httpAdapter } from "../../src/engine/adapter";
import { mockApi } from "../../src/demo/mockApi";

// The compile-time check (`satisfies EngineAdapter` in mockApi.ts) guarantees
// the shape. These tests guard the runtime behaviour Phase 7.0 relies on.
describe("EngineAdapter contract", () => {
  it("the demo adapter implements every engine method", () => {
    const missing = Object.keys(httpAdapter).filter(
      (k) => typeof (mockApi as Record<string, unknown>)[k] !== "function"
    );
    expect(missing).toEqual([]);
  });

  it("the demo adapter adds no methods the engine does not have", () => {
    const extra = Object.keys(mockApi).filter((k) => !(k in httpAdapter));
    expect(extra).toEqual([]);
  });

  it("engine-only capabilities reject with DemoUnavailableError instead of crashing", async () => {
    await expect(mockApi.electricalShadingCapability("demo-project", "m-1")).rejects.toBeInstanceOf(
      DemoUnavailableError
    );
    await expect(mockApi.electricalRegionMap("demo-project", "mi-1")).rejects.toThrow(/not available in demo mode/);
  });

  it("runs and runResult work in demo mode (SimulatePanel calls runResult)", async () => {
    const runs = await mockApi.runs("demo-project");
    expect(runs.length).toBeGreaterThan(0);
    const first = runs[0];
    const again = await mockApi.runResult("demo-project", first.simulation_run_id);
    expect(again.simulation_run_id).toBe(first.simulation_run_id);
    await expect(mockApi.runResult("demo-project", "no-such-run")).rejects.toThrow(/Unknown run/);
  });
});
