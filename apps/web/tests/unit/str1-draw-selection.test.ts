import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it } from "vitest";
import { rememberDrawSelection } from "../../src/canvas/PlanCanvas";
import { resetStore, uiStore } from "../../src/state/store";

beforeEach(() => resetStore());

describe.each(["surface", "obstacle", "keepout"] as const)("pending %s draw", (kind) => {
  async function replyAfterSelection(initial: string[], during?: string[]) {
    const { dispatch } = uiStore.getState();
    dispatch({ type: "setTool", tool: kind });
    dispatch({ type: "select", ids: initial });
    const selectDrawn = rememberDrawSelection();
    let resolve!: (id: string) => void;
    const reply = new Promise<string>((done) => { resolve = done; });
    const pending = reply.then(selectDrawn);
    if (during) dispatch({ type: "select", ids: during });
    resolve(`new-${kind}`);
    await pending;
    expect(uiStore.getState().state.tool).toBe("select");
    return uiStore.getState().state.selection;
  }

  it("keeps a selection made while the reply is pending", async () => {
    expect(await replyAfterSelection(["old"], ["chosen"])).toEqual(["chosen"]);
  });

  it("keeps a selection cleared while the reply is pending", async () => {
    expect(await replyAfterSelection(["old"], [])).toEqual([]);
  });

  it.each([[], ["old"], ["old", "other"]])("selects the new entity with unchanged selection %j", async (...initial) => {
    expect(await replyAfterSelection(initial)).toEqual([`new-${kind}`]);
  });

  it("compares selection values after the store replaces the array", async () => {
    expect(await replyAfterSelection(["old"], ["old"])).toEqual([`new-${kind}`]);
  });
});

it("uses the shared selection guard in all three draw reply paths", () => {
  const source = readFileSync(new URL("../../src/canvas/PlanCanvas.tsx", import.meta.url), "utf8");
  const draw = source.slice(source.indexOf("async function finishPolygon"), source.indexOf("function commitRotate"));
  expect(draw.indexOf("const selectDrawn = rememberDrawSelection()")).toBeLessThan(draw.indexOf('if (kind === "surface")'));
  expect(draw.match(/if \(v\) selectDrawn\(v\.bundle\.scene\.surfaces\.at\(-1\)!\.surface_id\)/g)).toHaveLength(2);
  expect(draw.match(/if \(v\) selectDrawn\(v\.bundle\.scene\.obstacles\.at\(-1\)!\.obstacle_id\)/g)).toHaveLength(1);
  expect(draw).not.toContain('type: "select"');
});
