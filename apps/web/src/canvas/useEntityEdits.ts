import { fieldSupportIds, isExplicitField } from "../types";
import { useCallback } from "react";
import { engine } from "../client";
import i18n from "../i18n";
import { bounds, scalePoly, translatePoly, validatePolygon, type Vec2, type PlaneDef, uiPlaneToEngine } from "../geometry";
import { uiStore, useActions, useUI, type Entity } from "../state/store";
import { sceneEdit, dependentSceneEdit } from "../state/history";
import { anchoredRectangle, ownBox, ownAxesDelta, edgeNormal, isRectangle, offsetEdge, rotateClockwise, setEdgeLength } from "./plan/edit";
import { newCommandId, type SceneCommandInput, type SceneConflictOptions, type ReferenceAnchor } from "../types";

export function entityReferenceAnchor(e: Entity): ReferenceAnchor {
  const scene = uiStore.getState().state.view?.bundle.scene;
  return (e as Entity & { reference_anchor?: ReferenceAnchor }).reference_anchor
    ?? (scene?.surfaces.find(s => s.surface_id === e.id) ?? scene?.obstacles.find(o => o.obstacle_id === e.id))?.reference_anchor
    ?? { u: "start", v: "start" };
}

/** The exact vector used by offsetEdge's browser preview (DEC-44). */
export function edgeMoveParameters(polygon: Vec2[], edge_index: number, offset: number) {
  const [nx, ny] = edgeNormal(polygon, edge_index);
  return { edge_index, dx_m: nx * offset, dy_m: ny * offset };
}

/** Engine commands cannot consume geometry with unsaved local edits. */
export async function entitySceneCommand(e: Entity, command_type: SceneCommandInput["command_type"], parameters: Record<string, unknown>) {
  const { state, toast } = uiStore.getState();
  if (e.modified || state.entities.some((current) => current.id === e.id && current.modified)) { toast("info", i18n.t("s7b.discardReason")); return; }
  const projectId = state.view?.bundle.project.project_id;
  if (!projectId || e.locked) return;
  if (command_type !== "set_reference_anchor" && state.view?.bundle.scene.pv_fields.some(f => isExplicitField(f) && fieldSupportIds(f).includes(e.id))) { toast("info", i18n.t("mesh1.noRefill")); return; }
  const hosted = !["edit_elevation", "edit_plane", "set_reference_anchor"].includes(command_type) && (e.hostsPvField || state.view?.bundle.scene.pv_fields.some((f) => fieldSupportIds(f).includes(e.id)));
  const command = { command_id: newCommandId(), command_type, target_entity_ids: [e.id], parameters };
  const op = (options: SceneConflictOptions) => command_type === "move"
    ? engine.moveSceneEntity(projectId, { entity_id: e.id, dx_m: Number(parameters.dx_m), dy_m: Number(parameters.dy_m) }, options)
    : engine.sceneCommand(projectId, command, options);
  if (hosted) return dependentSceneEdit("Editing roof and PV fields", op);
  return sceneEdit("Editing scene", (options) => op(options) as Promise<import("../types").ProjectView>);
}

/** Scene edits share busy state, conflict previews and concurrency reloads. */
export function useEntityEdits() {
  const { dispatch, toast } = useActions();
  const projectId = useUI((s) => s.view?.bundle.project.project_id ?? null);

  const commitGeometry = useCallback(
    (e: Entity, polygon: Vec2[], holes: Vec2[][], pendingId: string) => {
      const issues = validatePolygon(polygon);
      if (issues.length) {
        toast("error", `Edit rejected: ${issues[0].message}`);
        return;
      }
      dispatch({
        type: "updateEntity",
        id: e.id,
        patch: {
          polygon,
          holes,
          modified: e.source === "engine" ? true : e.modified,
          pending: e.source === "engine" ? [...new Set([...e.pending, pendingId])] : e.pending
        }
      });
      if (e.source === "engine") toast("pending", `Local edit kept as draft. Commit needs ${pendingId} endpoint.`);
    },
    [dispatch, toast]
  );

  const commitMove = useCallback(
    async (e: Entity, d: Vec2) => {
      if (Math.abs(d[0]) < 1e-9 && Math.abs(d[1]) < 1e-9) return;
      if (e.source === "engine") return entitySceneCommand(e, "move", { dx_m: d[0], dy_m: d[1] });
      commitGeometry(e, translatePoly(e.polygon, d), e.holes.map((h) => translatePoly(h, d)), "editVertices");
    },
    [commitGeometry]
  );

  const rotate = async (e: Entity, pivot: Vec2, angle: number) => {
    if (e.source === "engine") return entitySceneCommand(e, "rotate", { angle_deg: angle, origin: pivot });
    commitGeometry(e, rotateClockwise(e.polygon, pivot, angle), e.holes.map((h) => rotateClockwise(h, pivot, angle)), "editVertices");
  };
  const setReferenceAnchor = async (e: Entity, anchor: ReferenceAnchor) => {
    if (e.locked) return;
    if (e.source === "engine") return entitySceneCommand(e, "set_reference_anchor", anchor);
    const patch = { reference_anchor: anchor, pending: e.pending };
    dispatch({ type: "updateEntity", id: e.id, patch });
  };
  const setPosition = (e: Entity, axis: 0 | 1, value: number) => {
    const point = ownBox(e.polygon, entityReferenceAnchor(e)).point;
    return commitMove(e, axis === 0 ? [value - point[0], 0] : [0, value - point[1]]);
  };
  const setOrientation = (e: Entity, bearing: number) => {
    const box = ownBox(e.polygon, entityReferenceAnchor(e));
    return rotate(e, box.point, bearing - box.bearing);
  };
  const moveBy = (e: Entity, delta: Vec2, ownAxes: boolean) => commitMove(e, ownAxes ? ownAxesDelta(e.polygon, ...delta) : delta);
  const commitRing = (e: Entity, ring: number, vertices: Vec2[]) => commitGeometry(e,
    ring === 0 ? vertices : e.polygon,
    ring === 0 ? e.holes : e.holes.map((h, i) => i === ring - 1 ? vertices : h), "editVertices");
  const moveVertex = async (e: Entity, index: number, target: Vec2, ring = 0) => {
    if (e.source === "engine") return entitySceneCommand(e, "move_vertex", { ...(ring ? { ring } : {}), vertex_index: index, target_x_m: target[0], target_y_m: target[1] });
    commitRing(e, ring, (ring === 0 ? e.polygon : e.holes[ring - 1]).map((p, i) => i === index ? target : p));
  };
  const editDimension = async (e: Entity, edge: number, length: number) => {
    const preserve = isRectangle(e.polygon) ? "rectangle" : "start";
    if (e.source === "engine") return entitySceneCommand(e, "edit_exact_dimension", { edge_index: edge, length_m: length, preserve });
    commitGeometry(e, preserve === "rectangle" ? anchoredRectangle(e.polygon, edge, length, entityReferenceAnchor(e)) : setEdgeLength(e.polygon, edge, length, preserve), e.holes, "editVertices");
  };
  const insertVertex = async (e: Entity, edge: number, point: Vec2, ring = 0) => {
    if (e.source === "engine") return entitySceneCommand(e, "insert_vertex", { ...(ring ? { ring } : {}), edge_index: edge, x_m: point[0], y_m: point[1] });
    const points = ring === 0 ? e.polygon : e.holes[ring - 1];
    commitRing(e, ring, [...points.slice(0, edge + 1), point, ...points.slice(edge + 1)]);
  };
  const deleteVertex = async (e: Entity, index: number, ring = 0) => {
    if (e.source === "engine") return entitySceneCommand(e, "delete_vertex", { ...(ring ? { ring } : {}), vertex_index: index });
    commitRing(e, ring, (ring === 0 ? e.polygon : e.holes[ring - 1]).filter((_, i) => i !== index));
  };
  const moveEdge = async (e: Entity, edge: number, offset: number, ring = 0) => {
    if (e.source === "engine") return entitySceneCommand(e, "move_edge", { ...edgeMoveParameters(ring ? e.holes[ring - 1] : e.polygon, edge, offset), ...(ring ? { ring } : {}) });
    commitRing(e, ring, offsetEdge(ring === 0 ? e.polygon : e.holes[ring - 1], edge, offset));
  };
  const editPlane = async (e: Entity, plane: PlaneDef) => {
    try {
      const parameters = uiPlaneToEngine(e.polygon, plane);
      if (e.source === "engine") {
        // The equivalent UI mode is a display preference, never a geometry draft.
        const view = await entitySceneCommand(e, "edit_plane", { ...parameters });
        if (view) dispatch({ type: "updateEntity", id: e.id, patch: { plane }, history: false });
        return view;
      }
      dispatch({ type: "updateEntity", id: e.id, patch: { plane } });
    } catch (error) {
      toast("error", error instanceof Error && error.name === "AmbiguousEdgePlaneError" ? i18n.t("s11b.ambiguousEdge") : String(error instanceof Error ? error.message : error));
    }
  };
  const addHole = async (e: Entity, vertices: Vec2[]) => {
    if (e.source === "engine") return entitySceneCommand(e, "add_hole", { vertices });
    commitGeometry(e, e.polygon, [...e.holes, vertices], "editVertices");
  };
  const removeHole = async (e: Entity, hole_index: number) => {
    if (e.source === "engine") return entitySceneCommand(e, "remove_hole", { hole_index });
    commitGeometry(e, e.polygon, e.holes.filter((_, i) => i !== hole_index), "editVertices");
  };
  const editHeight = async (e: Entity, height_m: number) => {
    if (e.source === "engine") return entitySceneCommand(e, "edit_height", { height_m });
    dispatch({ type: "updateEntity", id: e.id, patch: { height_m } });
  };
  const resize = async (e: Entity, origin: Vec2, factor: number) => {
    if (e.source === "engine") return entitySceneCommand(e, "scale", { factor, origin });
    commitGeometry(e, scalePoly(e.polygon, origin, factor), e.holes.map((hole) => scalePoly(hole, origin, factor)), "editVertices");
  };
  const setBaseElevation = async (e: Entity, z: number) => {
    if (e.source === "engine") return entitySceneCommand(e, "edit_elevation", { base_elevation_m: z });
    dispatch({ type: "updateEntity", id: e.id, patch: { plane: { mode: "flat", z_m: z } } });
  };
  const raise = async (e: Entity, dz: number) => {
    if (Math.abs(dz) < 1e-9) return;
    if (e.plane.mode === "flat") return setBaseElevation(e, e.plane.z_m + dz);
    const plane = e.plane.mode === "edge_tilt" ? { ...e.plane, zRef_m: e.plane.zRef_m + dz } : { ...e.plane, z_m: e.plane.z_m + dz };
    return editPlane(e, plane);
  };
  const deleteEntities = async (entities: Entity[]) => {
    if (entities.some((e) => e.source === "engine" && (e.modified || uiStore.getState().state.entities.some((current) => current.id === e.id && current.modified)))) { toast("info", i18n.t("s7b.discardReason")); return; }
    const ids = entities.filter((e) => e.source === "engine").map((e) => e.id);
    const deleteDrafts = () => dispatch({ type: "deleteEntities", ids: entities.filter((e) => e.source === "draft").map(e => e.id), mergeEngine: ids.length > 0 });
    if (ids.length) {
      if (!projectId) return;
      if (uiStore.getState().state.view?.bundle.scene.pv_fields.some(f => isExplicitField(f) && fieldSupportIds(f).some(id => ids.includes(id)))) { toast("info", i18n.t("mesh1.noRefill")); return; }
      const command: SceneCommandInput = { command_id: newCommandId(), command_type: "delete", target_entity_ids: ids, parameters: {} };
      if (uiStore.getState().state.view?.bundle.scene.pv_fields.some((f) => fieldSupportIds(f).some(id => ids.includes(id)))) {
        return dependentSceneEdit("Deleting roof and PV fields", (options) => engine.sceneCommand(projectId, command, options), deleteDrafts);
      }
      if (!await sceneEdit("Deleting scene entities", (options) => engine.sceneCommand(projectId, command, options))) return;
    }
    deleteDrafts();
  };
  /**
   * Duplicate beside the original, or (UX3 paste) at `offset`, with a roof's PV when `withPv`: one engine copy
   * command (one undo step), or a local copy of a draft.
   */
  const duplicate = async (e: Entity, options: { offset?: Vec2; withPv?: boolean } = {}) => {
    const box = bounds([e.polygon]);
    const [dx, dy] = options.offset ?? [box.maxX - box.minX + 1, 0];
    if (e.source === "draft") {
      dispatch({ type: "addEntity", entity: { ...e, id: `${e.id}-copy-${Date.now().toString(36)}`, name: `${e.name} copy`,
        polygon: translatePoly(e.polygon, [dx, dy]), holes: e.holes.map((h) => translatePoly(h, [dx, dy])), locked: false, hidden: false } });
      return;
    }
    const { state } = uiStore.getState();
    if (e.modified || state.entities.some((current) => current.id === e.id && current.modified)) { toast("info", i18n.t("s7b.discardReason")); return; }
    if (!projectId) return;
    const withPv = options.withPv === true && e.kind === "surface";
    const command = { command_id: newCommandId(), command_type: "copy" as const, target_entity_ids: [e.id], parameters: { dx_m: dx, dy_m: dy, ...(withPv ? { with_pv: true } : {}) } };
    const label = options.offset ? i18n.t("ux3.pasting", { name: e.name }) : i18n.t("ux2.duplicating", { name: e.name });
    return sceneEdit(label, (conflict) => engine.sceneCommand(projectId, command, conflict) as Promise<import("../types").ProjectView>);
  };

  return { setReferenceAnchor, setPosition, setOrientation, moveBy, editPlane, addHole, removeHole, commitGeometry, commitMove, rotate, moveVertex, insertVertex, deleteVertex, moveEdge, editHeight, editDimension, resize, setBaseElevation, raise, deleteEntities, duplicate };
}
