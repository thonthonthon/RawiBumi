import { describe, expect, it } from "vitest";
import { railSteps } from "../../src/modules/registry";
import { demoSystemsOverview, mockApi, setDemoLatency } from "../../src/demo/mockApi";
import { orientationGroupLabel, suggestedBuildingCommands } from "../../src/panels/SystemsPanel";
import { stepStates, selectModel } from "../../src/state/derived";
import { resetStore, uiStore } from "../../src/state/store";

async function fixture() {
  const view = structuredClone(await mockApi.project("demo-project"));
  const definition = view.catalog.modules[0];
  view.bundle.scene.buildings = [];
  view.bundle.scene.surfaces = [0, 1.9, 62.9].map((x, i) => ({ surface_id: `s${i}`, name: `Roof ${i}`, surface_type: "flat_roof", base_elevation_m: 0,
    boundary_2d: { vertices: [[x, 0], [x + 1, 0], [x + 1, 3], [x, 3]], holes: [] } }));
  view.bundle.scene.pv_fields = [10, 10.7, 11.4].map((tilt, i) => ({ pv_field_id: `f${i}`, name: `Field ${i}`, support_surface_id: `s${i}`,
    module_definition_revision_id: definition.revision_id, row_count: 1, modules_per_row: 1, orientation: "portrait", azimuth_deg: 0, tilt_deg: tilt }));
  view.bundle.scene.module_instances = [0, 1, 2].map(i => ({ module_instance_id: `m${i}`, pv_field_id: `f${i}`, module_definition_revision_id: definition.revision_id, enabled: true }));
  return view;
}

setDemoLatency(0);
describe("USE4A systems", () => {
  it("uses the workflow rail order and numbered shortcuts", () => {
    expect(railSteps().map(s => [s.id, s.shortcut])).toEqual([
      ["site", "1"], ["components", "2"], ["scene", "3"], ["layout", "4"], ["systems", "5"],
      ["electrical", "6"], ["meteo", "7"], ["losses", "8"], ["simulate", "9"], ["results", "0"], ["export", undefined]
    ]);
  });
  it("suggestions map to one group per unmatched cluster", async () => {
    const overview = demoSystemsOverview(await fixture());
    const commands = suggestedBuildingCommands(overview);
    expect(commands.map(c => [c.command_type, c.target_entity_ids, c.parameters.name])).toEqual([
      ["group", ["s0", "s1"], "Building 1"], ["group", ["s2"], "Building 2"]
    ]);
    expect(commands.every(c => typeof c.parameters.group_id === "string")).toBe(true);
    overview.suggested_buildings[0].matches_confirmed = true;
    expect(suggestedBuildingCommands(overview)).toEqual([commands[1]]);
  });
  it("demo uses union-find distance suggestions and complete linkage for normals", async () => {
    const view = await fixture();
    const before = JSON.stringify(view);
    const overview = demoSystemsOverview(view);
    expect(JSON.stringify(view)).toBe(before);
    expect(overview.suggested_buildings.map(s => s.surface_ids)).toEqual([["s0", "s1"], ["s2"]]);
    expect(overview.orientation_groups.map(g => g.pv_field_ids)).toEqual([["f0", "f1"], ["f2"]]);
    expect(overview.orientation_groups.map(g => g.module_count)).toEqual([2, 1]);
    expect(overview.distances[2].distance_m).toBeCloseTo(60, 10);
    expect(overview.distances[2].over_threshold).toBe(true);
    view.bundle.project.distance_warning_m = 100;
    expect(demoSystemsOverview(view).distances.every(d => !d.over_threshold)).toBe(true);
    view.bundle.scene.surfaces[0].group_id = "a"; view.bundle.scene.surfaces[1].group_id = "a"; view.bundle.scene.surfaces[2].group_id = "b";
    view.bundle.scene.buildings = [{ building_id: "a", name: "Main" }, { building_id: "b", name: "Far" }];
    expect(demoSystemsOverview(view).buildings.map(b => [b.name, b.module_count])).toEqual([["Main", 2], ["Far", 1]]);
    expect(demoSystemsOverview(view).suggested_buildings.every(s => s.matches_confirmed)).toBe(true);
  });
  it("demo commands enforce names, preserve module/string data, and undo grouping", async () => {
    const created = await mockApi.createProject({ name: "Systems", latitude_deg: -6.2, longitude_deg: 106.8, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" });
    const view = await mockApi.addSurface(created.bundle.project.project_id, { name: "Roof", origin_x_m: 0, origin_y_m: 0,
      width_m: 10, height_m: 5, base_elevation_m: 6, surface_type: "flat_roof" });
    const pid = view.bundle.project.project_id, sid = view.bundle.scene.surfaces[0].surface_id;
    const before = structuredClone(view.bundle);
    await expect(mockApi.sceneCommand(pid, { command_type: "group", target_entity_ids: [sid], parameters: { group_id: "g" } })).rejects.toThrow("a new building requires a name");
    const grouped = await mockApi.sceneCommand(pid, { command_type: "group", target_entity_ids: [sid], parameters: { group_id: "g", name: "Main" } });
    expect(grouped.bundle.scene.buildings).toEqual([{ building_id: "g", name: "Main" }]);
    expect(grouped.bundle.scene.module_instances).toEqual(before.scene.module_instances);
    expect(grouped.bundle.electrical_design.strings).toEqual(before.electrical_design.strings);
    const undone = await mockApi.undo(pid);
    expect(undone.bundle.scene.buildings).toEqual(before.scene.buildings);
    await mockApi.sceneCommand(pid, { command_type: "group", target_entity_ids: [sid], parameters: { group_id: "g", name: "Main" } });
    const renamed = await mockApi.sceneCommand(pid, { command_type: "group", target_entity_ids: [sid], parameters: { group_id: "g", name: "Renamed" } });
    expect(renamed.bundle.scene.buildings![0].name).toBe("Renamed");
    const ungrouped = await mockApi.sceneCommand(pid, { command_type: "ungroup", target_entity_ids: [sid], parameters: {} });
    expect(ungrouped.bundle.scene.buildings).toEqual([]);
  });
  it("distinguishes duplicate orientation labels by their module models", async () => {
    const view = await fixture();
    const original = view.catalog.modules[0];
    const other = { ...original, revision_id: "other-r1", model: "Other module" };
    view.catalog.modules.push(other);
    view.bundle.scene.module_instances[1].module_definition_revision_id = other.revision_id;
    view.bundle.scene.pv_fields[1] = { ...view.bundle.scene.pv_fields[0], pv_field_id: "f1", support_surface_id: "s1" };
    const groups = demoSystemsOverview(view).orientation_groups;
    expect(groups.map(g => g.module_definition_revision_ids)).toEqual([[original.revision_id], [other.revision_id], [original.revision_id]]);
    expect(orientationGroupLabel(groups[0], groups, view.catalog.modules)).toBe(`10.0° / 0.0° · ${original.model}`);
    expect(orientationGroupLabel(groups[1], groups, view.catalog.modules)).toBe("10.0° / 0.0° · Other module");
    expect(orientationGroupLabel(groups[2], groups, view.catalog.modules)).toBe(groups[2].label);
    expect(orientationGroupLabel(groups[0], [groups[0]], view.catalog.modules)).toBe(groups[0].label);
  });
  it("rail state changes only when a building is confirmed", async () => {
    resetStore();
    const view = await fixture();
    uiStore.getState().dispatch({ type: "setView", view });
    expect(stepStates(selectModel(uiStore.getState().state)).systems).toBe("none");
    view.bundle.scene.buildings = [{ building_id: "a", name: "Main" }];
    uiStore.getState().dispatch({ type: "setView", view });
    expect(stepStates(selectModel(uiStore.getState().state)).systems).toBe("valid");
  });
});
