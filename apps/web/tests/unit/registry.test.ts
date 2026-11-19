import { afterEach, describe, expect, it } from "vitest";
import { installedModules, railSteps, stepDef } from "../../src/modules/registry";
import { can, setEntitlementSource } from "../../src/platform/entitlements";

describe("module registry", () => {
  afterEach(() => setEntitlementSource(null));

  it("the core module provides the eleven steps once, in workflow order", () => {
    expect(railSteps().map((s) => s.id)).toEqual(["site", "components", "scene", "layout", "systems", "electrical", "meteo", "losses", "simulate", "results", "export"]);
  });

  it("every step has a label key and a layout", () => {
    for (const s of railSteps()) {
      expect(s.labelKey).toMatch(/^steps\./);
      expect(["workspace", "full"]).toContain(s.layout);
    }
    expect(stepDef("results")?.layout).toBe("full");
  });

  it("module ids are unique", () => {
    const ids = installedModules().map((m) => m.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("hides a step whose feature is not entitled", () => {
    setEntitlementSource((f) => f !== "core.simulate");
    expect(railSteps().some((s) => s.id === "simulate")).toBe(false);
  });

  it("self-hosted default: free features on, paid features off", () => {
    expect(can("core.design")).toBe(true);
    expect(can("electrical.sld-full")).toBe(false);
    expect(can("module.finmod")).toBe(false);
  });
});
