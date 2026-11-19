import { afterEach, describe, expect, it, vi } from "vitest";
import { flag } from "../../src/platform/flags";
import { setTelemetrySink, track } from "../../src/platform/telemetry";

describe("platform extension points", () => {
  afterEach(() => setTelemetrySink(null));

  it("telemetry is a no-op until a sink is installed", () => {
    expect(() => track("step.viewed", { step: "site" })).not.toThrow();
  });

  it("telemetry forwards events to the installed sink", () => {
    const sink = vi.fn();
    setTelemetrySink(sink);
    track("command.run", { id: "project.save" });
    expect(sink).toHaveBeenCalledWith("command.run", { id: "project.save" });
  });

  it("a failing sink never breaks the caller", () => {
    setTelemetrySink(() => {
      throw new Error("network");
    });
    expect(() => track("project.opened")).not.toThrow();
  });

  it("flags have defaults", () => {
    expect(flag("module-registry-debug")).toBe(false);
  });
});
