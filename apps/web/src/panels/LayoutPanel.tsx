import { isExplicitField, isGeneratedField, fieldSupportIds, moduleNameplateW } from "../types";
import { componentCatalogLabel } from "../types";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { DEMO, engine } from "../client";
import { legacyFieldInput, legacyRefillRequest, missingRefillParameters, pvFieldChanges, moduleCountOf, slotOf, type Alignment, type FillZoneRequest, type LeftoverDepth, type Orientation, type StoredPvField, type PvFieldChanges, type PvFieldUpdatePreview, type PvFieldDeletePreview } from "../engine/layout";
import { ApiError } from "../types";
import type { ShadingFreePitch } from "../types";
import { ModalDialog } from "../ui/ModalDialog";
import { pickable, useShowTestComponents } from "../ui/testComponents";
import { ComponentFilterBar, filterComponents, NO_FILTER } from "../ui/ComponentFilter";
import { bearingDeg, centroid, type Vec2 } from "../geometry";
import { entitySceneCommand } from "../canvas/useEntityEdits";
import { NotWiredError } from "../pending";
import { engineCommand } from "../state/history";
import { useActions, useForm, useUI } from "../state/store";
import { modulesPerField } from "../state/derived";
import { tablesOfModules, useTableEdits } from "../canvas/useTableEdits";
import { GlyphBlocked, GlyphInfo, GlyphWarning } from "../ui/icons";
import { Button, Check, Field, FieldGroup, fmt, NotWired, NumberInput, Section, Segmented, Select } from "../ui/kit";

type PitchMode = "fixed_aisle" | "gcr" | "shading_free";

/** The fill-zone form (B5). Lengths in metres, angles in degrees. */
export interface FillForm {
  fieldId: string | null;
  name: string;
  surface: string;
  module: string;
  orientation: Orientation;
  tilt: number;
  azimuth: number;
  /** USE3: parallel to the roof plane (tilt, and the azimuth of a sloped roof, come from the roof). */
  parallel: boolean;
  mount: number;
  rows: number;
  gap: number;
  inGap: number;
  pitchMode: PitchMode;
  aisle: number;
  gcr: number;
  sunElevation: number;
  sunOffset: number;
  sameSetback: boolean;
  setback: number;
  edgeSetbacks: number[];
  keepout: number;
  leftover: LeftoverDepth;
  walkEvery: number; // 0: none
  walkWidth: number;
  cap: number; // 0: none
  rowAlign: Alignment;
  depthAlign: Alignment | null; // null: the row grid that fits the most modules
}

export const FILL_DEFAULTS: Omit<FillForm, "surface" | "module"> = {
  fieldId: null,
  name: "Roof array",
  orientation: "portrait",
  tilt: 10,
  azimuth: 0,
  parallel: false,
  mount: 0.2,
  rows: 1,
  gap: 0.02,
  inGap: 0.02,
  pitchMode: "fixed_aisle",
  aisle: 0.6,
  gcr: 0.5,
  sunElevation: 30,
  sunOffset: 0,
  sameSetback: true,
  setback: 0.3,
  edgeSetbacks: [],
  keepout: 0.3,
  leftover: "smaller_table",
  walkEvery: 0,
  walkWidth: 0.6,
  cap: 0,
  rowAlign: "start",
  depthAlign: null
};

export function requestOf(f: FillForm, edgeCount: number): FillZoneRequest {
  return {
    pv_field_id: f.fieldId,
    name: f.name,
    support_surface_id: f.surface,
    module_definition_revision_id: f.module,
    orientation: f.orientation,
    azimuth_deg: f.azimuth,
    tilt_deg: f.tilt,
    mounting_height_m: f.mount,
    rows_per_table: f.rows,
    module_gap_m: f.gap,
    in_table_gap_m: f.inGap,
    pitch:
      f.pitchMode === "fixed_aisle"
        ? { mode: "fixed_aisle", aisle_m: f.aisle }
        : f.pitchMode === "gcr"
          ? { mode: "gcr", gcr: f.gcr }
          : { mode: "shading_free", sun_elevation_deg: f.sunElevation, sun_azimuth_offset_deg: f.sunOffset },
    edge_setbacks_m: Array.from({ length: edgeCount }, (_, i) => (f.sameSetback ? f.setback : (f.edgeSetbacks[i] ?? f.setback))),
    keepout_offset_m: f.keepout,
    leftover_depth: f.leftover,
    walkway: f.walkEvery > 0 ? { every_modules: f.walkEvery, width_m: f.walkWidth } : null,
    max_table_columns: f.cap > 0 ? f.cap : null,
    row_alignment: f.rowAlign,
    depth_alignment: f.depthAlign
  };
}

function formOf(r: FillZoneRequest, fieldId: string): Partial<FillForm> {
  const s = r.edge_setbacks_m;
  return {
    fieldId,
    name: r.name,
    surface: r.support_surface_id,
    module: r.module_definition_revision_id,
    orientation: r.orientation,
    tilt: r.tilt_deg,
    azimuth: r.azimuth_deg,
    mount: r.mounting_height_m,
    rows: r.rows_per_table,
    gap: r.module_gap_m,
    inGap: r.in_table_gap_m,
    pitchMode: r.pitch.mode,
    ...(r.pitch.mode === "fixed_aisle" ? { aisle: r.pitch.aisle_m } : r.pitch.mode === "gcr" ? { gcr: r.pitch.gcr } : { sunElevation: r.pitch.sun_elevation_deg, sunOffset: r.pitch.sun_azimuth_offset_deg }),
    sameSetback: s.every((x) => Math.abs(x - (s[0] ?? 0)) < 1e-9),
    setback: s[0] ?? 0,
    edgeSetbacks: s.slice(),
    keepout: r.keepout_offset_m,
    leftover: r.leftover_depth,
    walkEvery: r.walkway?.every_modules ?? 0,
    walkWidth: r.walkway?.width_m ?? 0.6,
    cap: r.max_table_columns ?? 0,
    rowAlign: r.row_alignment ?? "start",
    depthAlign: r.depth_alignment ?? null
  };
}

type RoofPlane = { slope_deg?: number; azimuth_deg?: number } | undefined;

/** USE3: the tilt and azimuth a parallel-to-roof field takes; a flat roof keeps the row direction it was given. */
export function parallelMounting(f: Pick<FillForm, "tilt" | "azimuth" | "parallel">, roof: RoofPlane): { tilt: number; azimuth: number; azimuthFromRoof: boolean } {
  if (!f.parallel || !roof) return { tilt: f.tilt, azimuth: f.azimuth, azimuthFromRoof: false };
  const slope = roof.slope_deg ?? 0;
  return slope > 0 ? { tilt: slope, azimuth: roof.azimuth_deg ?? f.azimuth, azimuthFromRoof: true } : { tilt: 0, azimuth: f.azimuth, azimuthFromRoof: false };
}

/** USE3: a stored field is parallel to its roof when its tilt (and, on a sloped roof, its azimuth) match the roof's. */
export function isParallelToRoof(field: { tilt_deg: number; azimuth_deg: number }, roof: RoofPlane): boolean {
  if (!roof) return false;
  const slope = roof.slope_deg ?? 0;
  const near = (a: number, b: number) => Math.abs(a - b) < 1e-6;
  return slope > 0 ? near(field.tilt_deg, slope) && near(((field.azimuth_deg - (roof.azimuth_deg ?? 0)) % 360 + 360) % 360, 0) : near(field.tilt_deg, 0);
}

/**
 * USE3b: the roof edge whose outward normal is nearest the roof's downslope azimuth, when the two differ slightly
 * (0.05–5°). Rows follow the plane's azimuth, so such a roof packs rows slightly askew to its edge.
 */
export function edgeMisalignment(roof: { slope_deg?: number; azimuth_deg?: number; boundary_2d?: { vertices: [number, number][] } } | undefined):
  { edgeIndex: number; edgeAzimuth: number; delta: number } | null {
  const poly = roof?.boundary_2d?.vertices;
  if (!roof || !poly || poly.length < 3 || !(roof.slope_deg && roof.slope_deg > 0)) return null;
  const c = centroid(poly);
  let best: { edgeIndex: number; edgeAzimuth: number; delta: number } | null = null;
  poly.forEach((a, i) => {
    const b = poly[(i + 1) % poly.length];
    const mid: Vec2 = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    let n: Vec2 = [b[1] - a[1], -(b[0] - a[0])];
    if ((mid[0] - c[0]) * n[0] + (mid[1] - c[1]) * n[1] < 0) n = [-n[0], -n[1]];
    const bearing = bearingDeg(mid, [mid[0] + n[0], mid[1] + n[1]]);
    const delta = Math.abs((((bearing - (roof.azimuth_deg ?? 0)) % 360) + 540) % 360 - 180);
    if (!best || delta < best.delta) best = { edgeIndex: i, edgeAzimuth: bearing, delta };
  });
  return best && (best as { delta: number }).delta >= 0.05 && (best as { delta: number }).delta <= 5 ? best : null;
}

/** User names remain untouched; default names take the first free numeric suffix. */
export function uniqueFieldName(base: string, fields: ReadonlyArray<{ name: string }>): string {
  const names = new Set(fields.map((field) => field.name));
  let name = base, suffix = 2;
  while (names.has(name)) name = `${base} ${suffix++}`;
  return name;
}

/** Bearing an edge faces (its outward normal), 0° north, clockwise. */
function edgeFacing(poly: readonly Vec2[], i: number): number {
  let area = 0;
  for (let k = 0; k < poly.length; k++) area += poly[k][0] * poly[(k + 1) % poly.length][1] - poly[(k + 1) % poly.length][0] * poly[k][1];
  const a = poly[i];
  const b = poly[(i + 1) % poly.length];
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const n: Vec2 = area > 0 ? [dy, -dx] : [-dy, dx];
  return ((Math.atan2(n[0], n[1]) * 180) / Math.PI + 360) % 360;
}

export function LayoutPanel() {
  const { t } = useTranslation();
  const { dispatch, toast, run } = useActions();
  const s = useUI((st) => ({ view: st.view, entities: st.entities, selection: st.selection, preview: st.layoutPreview, modules: st.modules, busy: st.busy }));
  const v = s.view!;
  const pid = v.bundle.project.project_id;
  const surfaces = v.bundle.scene.surfaces;
  // USE-D7: test modules are hidden unless shown; the default is then the first real, simulation-ready module.
  const [showTest] = useShowTestComponents();
  const [modFilter, setModFilter] = useState(NO_FILTER);
  const choosable = pickable(v.catalog.modules, showTest);
  const readyModule = choosable.find((m) => m.simulation_ready) ?? choosable[0] ?? v.catalog.modules[0];
  // Keep an untouched form stable while asynchronous previews change panel state.
  const initialForm = useMemo(() => ({ ...FILL_DEFAULTS,
    name: uniqueFieldName(t("rf1.defaultName", { roof: surfaces[0]?.name ?? "" }), v.bundle.scene.pv_fields),
    surface: surfaces[0]?.surface_id ?? "", module: readyModule?.revision_id ?? ""
  }), [surfaces, readyModule, t, v.bundle.scene.pv_fields]);
  const [f, setF] = useForm<FillForm>("layout.fill", initialForm);
  const set = (patch: Partial<FillForm>) => setF({ ...f, ...patch });
  const tables = useMemo(() => v.table_layout?.tables ?? [], [v]);
  const requests = v.table_layout?.requests ?? {};
  const editing = v.bundle.scene.pv_fields.filter(isGeneratedField).find((field) => field.pv_field_id === f.fieldId);
  const legacyEditing = !!editing && !requests[editing.pv_field_id];
  const perField = modulesPerField({ modules: s.modules });
  const mod = v.catalog.modules.find((m) => m.revision_id === f.module);
  const surfaceEntity = s.entities.find((e) => e.id === f.surface);
  const edges = surfaceEntity?.polygon ?? [];
  const draftSurfaces = s.entities.filter((e) => e.kind === "surface" && e.source === "draft");
  const roofPlane = surfaces.find((surface) => surface.surface_id === f.surface);
  const mounting = parallelMounting(f, roofPlane);
  const skew = edgeMisalignment(roofPlane);
  const request = useMemo(() => requestOf({ ...f, tilt: mounting.tilt, azimuth: mounting.azimuth }, edges.length), [f, edges.length, mounting.tilt, mounting.azimuth]);
  // USE1 (USE-D8): the engine computes the shading-free pitch; the fill then applies it as the row pitch.
  const [sunPitch, setSunPitch] = useState<ShadingFreePitch | null>(null);
  useEffect(() => {
    setSunPitch(null);
    if (f.pitchMode !== "shading_free" || !mod) return;
    let live = true;
    const timer = window.setTimeout(() => {
      engine.shadingFreePitch(pid, { module_definition_revision_id: mod.revision_id, orientation: f.orientation, tilt_deg: f.tilt,
        design_sun_elevation_deg: f.sunElevation, sun_azimuth_offset_deg: f.sunOffset, rows_per_table: f.rows, module_gap_y_m: f.inGap })
        .then((r) => { if (live) setSunPitch(r); }).catch(() => { if (live) setSunPitch(null); });
    }, 250);
    return () => { live = false; window.clearTimeout(timer); };
  }, [pid, f.pitchMode, mod, f.orientation, f.tilt, f.sunElevation, f.sunOffset, f.rows, f.inGap]);
  const legacy = mod ? legacyFieldInput(request, mod, sunPitch?.row_pitch_m) : { input: null, reasons: [] as string[] };
  const mapped = legacyEditing && mod ? pvFieldChanges(request, editing, mod, sunPitch?.row_pitch_m) : null;
  // USE3b: with no setting changed, Re-fill re-packs the field on its current roof (an unchanged row pitch is enough
  // for the engine to pack again); the preview shows whether the module count changes.
  const refillChanges = mapped && !mapped.reasons.length
    ? (Object.keys(mapped.changes).length ? mapped.changes : { row_pitch_m: editing!.row_pitch_m }) : null;
  const targetFields = v.bundle.scene.pv_fields.filter((field) => fieldSupportIds(field).includes(f.surface))
    .sort((a, b) => a.pv_field_id < b.pv_field_id ? -1 : a.pv_field_id > b.pv_field_id ? 1 : 0);
  const occupied = !f.fieldId ? targetFields[0] : null;
  const roofName = surfaces.find((surface) => surface.surface_id === f.surface)?.name ?? f.surface;
  const demoModuleChange = DEMO && !!editing && f.module !== editing.module_definition_revision_id;
  const invalidAzimuth = (legacyEditing || !f.fieldId) && (!Number.isFinite(f.azimuth) || f.azimuth < 0 || f.azimuth >= 360);
  const [confirmation, setConfirmation] = useState<
    { kind: "refill"; preview: PvFieldUpdatePreview; changes: PvFieldChanges; moduleChange?: { before: string; after: string }; replaces?: boolean } |
    { kind: "delete"; preview: PvFieldDeletePreview } | null>(null);
  const [conflicts, setConflicts] = useState<Array<Record<string, unknown>>>([]);
  const captureConflicts = (error: unknown) => {
    if (error instanceof ApiError && error.detail && typeof error.detail === "object" && "conflicts" in error.detail && Array.isArray(error.detail.conflicts))
      setConflicts(error.detail.conflicts.filter((c): c is Record<string, unknown> => !!c && typeof c === "object"));
  };
  const openRefill = (field: import("../types").PvField) => {
    if (isExplicitField(field)) return;
    const module = v.catalog.modules.find((m) => m.revision_id === field.module_definition_revision_id);
    const edgeCount = s.entities.find((e) => e.id === field.support_surface_id)?.polygon.length ?? 0;
    const r = requests[field.pv_field_id] ?? (module ? legacyRefillRequest(field, module, edgeCount) : null);
    // An older incomplete field still becomes the target, but mapping blocks Apply.
    const parallel = isParallelToRoof(field, surfaces.find((surface) => surface.surface_id === field.support_surface_id));
    set(r ? { ...formOf(r, field.pv_field_id), parallel } : { fieldId: field.pv_field_id, surface: field.support_surface_id,
      name: field.name, module: field.module_definition_revision_id, parallel });
    setConflicts([]);
  };
  const defaultName = (view = v, excludedFieldId: string | null = null) => uniqueFieldName(t("rf1.defaultName", {
    roof: view.bundle.scene.surfaces.find((surface) => surface.surface_id === f.surface)?.name ?? f.surface
  }), view.bundle.scene.pv_fields.filter((field) => field.pv_field_id !== excludedFieldId));
  const leaveRefill = (view = v) => set({ fieldId: null, name: defaultName(view) });
  const targetRoof = (surface: string) => {
    const fields = v.bundle.scene.pv_fields.filter((field) => fieldSupportIds(field).includes(surface))
      .sort((a, b) => a.pv_field_id < b.pv_field_id ? -1 : a.pv_field_id > b.pv_field_id ? 1 : 0);
    if (surface === f.surface && !f.fieldId && !fields.length) return;
    if (fields.length && isGeneratedField(fields[0])) openRefill(fields[0]);
    else if (fields.length) { set({fieldId: null, surface}); setConflicts([]); }
    else {
      const roof = surfaces.find((item) => item.surface_id === surface);
      if (!roof) return;
      const nextDefault = uniqueFieldName(t("rf1.defaultName", { roof: roof.name }), v.bundle.scene.pv_fields);
      set({ fieldId: null, surface, name: !f.name || f.name === defaultName(v, f.fieldId) ? nextDefault : f.name });
      setConflicts([]);
    }
  };
  const selectedRoof = s.selection.length === 1
    ? s.entities.find((entity) => entity.id === s.selection[0] && entity.source === "engine" && entity.kind === "surface")?.id
    : undefined;
  // Only selection transitions retarget. A save or Cancel must not reopen re-fill.
  useEffect(() => { if (selectedRoof) targetRoof(selectedRoof); }, [selectedRoof, pid]);
  const cancel = () => {
    if (s.busy) return;
    setConfirmation(null);
    leaveRefill();
  };
  const [openId, setOpenId] = useForm<string | null>("layout.refillTarget", null);
  useEffect(() => {
    if (!openId) return;
    const field = v.bundle.scene.pv_fields.find((x) => x.pv_field_id === openId);
    if (field) openRefill(field);
    setOpenId(null);
  }, [openId]);
  const [previewState, setPreviewState] = useState<"idle" | "loading" | "unavailable" | "error">("idle");
  const [previewError, setPreviewError] = useState<string | null>(null);
  const edits = useTableEdits();
  const [move, setMove] = useState<Vec2>([1, 0]);

  // Live preview (B5): the engine fills the zone in both orientations before Apply.
  const seq = useRef(0);
  useEffect(() => {
    if (legacyEditing || occupied || !f.surface || !f.module || !surfaceEntity || surfaceEntity.source !== "engine") {
      ++seq.current;
      dispatch({ type: "setLayoutPreview", preview: null });
      return;
    }
    const n = ++seq.current;
    setPreviewState("loading");
    const timer = setTimeout(() => {
      engine.previewFill(pid, request).then(
        (p) => {
          if (n !== seq.current) return;
          dispatch({ type: "setLayoutPreview", preview: p });
          setPreviewState("idle");
          setPreviewError(null);
        },
        (err: unknown) => {
          if (n !== seq.current) return;
          dispatch({ type: "setLayoutPreview", preview: null });
          if (err instanceof NotWiredError) setPreviewState("unavailable");
          else {
            setPreviewState("error");
            setPreviewError(err instanceof Error ? err.message : String(err));
          }
        }
      );
    }, 180);
    return () => clearTimeout(timer);
  }, [pid, request, f.surface, f.module, surfaceEntity, dispatch, legacyEditing, !!occupied]);

  // The scene's drawing tools do not apply here: the layout step starts with Select.
  // The preview belongs to this panel; leaving the step clears it.
  useEffect(() => {
    dispatch({ type: "setTool", tool: "select" });
    return () => dispatch({ type: "setLayoutPreview", preview: null });
  }, [dispatch]);

  const preview = s.preview;
  // Apply only what the preview shows: the preview must be of the current form.
  const fresh = !!preview && JSON.stringify(preview.request) === JSON.stringify(request);
  const blocking = preview?.findings.filter((x) => x.severity === "blocking") ?? [];
  // UXF2 (U2-21): one button. On a roof that already has a layout, Apply fill re-fills that field with this form, after a
  // confirmation that the existing layout is replaced (there is no separate "Re-fill" step).
  const occupiedMapping = occupied && !isExplicitField(occupied) && mod
    ? pvFieldChanges({ ...request, pv_field_id: occupied.pv_field_id }, occupied, mod, sunPitch?.row_pitch_m) : null;
  const occupiedChanges = occupiedMapping && !occupiedMapping.reasons.length
    ? (Object.keys(occupiedMapping.changes).length ? occupiedMapping.changes : { row_pitch_m: (occupied as { row_pitch_m?: number }).row_pitch_m! }) : null;
  const canApply = !s.busy && (!occupied || !!occupiedChanges) && !invalidAzimuth && !!f.surface && !!f.module && (occupied ? true : demoModuleChange ? true : legacyEditing
    ? !!refillChanges
    : (preview ? fresh && blocking.length === 0 && preview.module_count > 0 : previewState === "unavailable" && !!legacy.input));

  async function apply() {
    if (!canApply) return;
    if (occupied && occupiedChanges) {
      setConflicts([]);
      const result = await run(t("s7a.previewRefill"), async () => {
        try { return await engine.previewPvFieldUpdate(pid, occupied.pv_field_id, occupiedChanges); }
        catch (error) { captureConflicts(error); throw error; }
      });
      if (result) {
        if (result.conflicts.length) setConflicts(result.conflicts.filter((c): c is Record<string, unknown> => !!c && typeof c === "object"));
        else setConfirmation({ kind: "refill", preview: result, changes: occupiedChanges, replaces: true });
      }
      return;
    }
    if (demoModuleChange && editing) {
      await run(t("s7a.previewRefill"), () => engine.previewPvFieldUpdate(pid, editing.pv_field_id, { module_definition_revision_id: f.module }));
      return;
    }
    if (legacyEditing && mapped) {
      setConflicts([]);
      const result = await run(t("s7a.previewRefill"), async () => {
        try { return await engine.previewPvFieldUpdate(pid, editing.pv_field_id, refillChanges!); }
        catch (error) {
          captureConflicts(error);
          throw error;
        }
      });
      if (result) {
        if (result.conflicts.length) setConflicts(result.conflicts.filter((c): c is Record<string, unknown> => !!c && typeof c === "object"));
        else setConfirmation({ kind: "refill", preview: result, changes: refillChanges!,
          ...(mapped.changes.module_definition_revision_id ? { moduleChange: {
            before: v.catalog.modules.find((m) => m.revision_id === editing.module_definition_revision_id)?.model ?? editing.module_definition_revision_id,
            after: mod?.model ?? f.module
          } } : {}) });
      }
      return;
    }
    const res = await engineCommand(f.fieldId ? t("layout.refilling") : t("layout.filling"), () => engine.applyFill(pid, request, preview ? null : legacy.input));
    if (!res) return;
    dispatch({ type: "setLayoutPreview", preview: null });
    const fieldId = f.fieldId ?? res.bundle.scene.pv_fields[res.bundle.scene.pv_fields.length - 1]?.pv_field_id ?? null;
    // Preserve the existing editing path only after a new demo table fill.
    if (f.fieldId) leaveRefill(res);
    else if (res.table_layout?.requests[fieldId ?? ""]) set({ fieldId });
    else leaveRefill(res);
    toast("ok", `${f.fieldId ? t("layout.refilled") : t("layout.filled")} · ${roofName}`);
  }

  async function deleteField(fieldId: string) {
    const preview = await run(t("s7a.previewDelete"), () => engine.previewPvFieldDelete(pid, fieldId));
    if (preview) setConfirmation({ kind: "delete", preview });
  }

  async function confirm() {
    if (!confirmation || s.busy) return;
    const item = confirmation;
    const flags = item.preview.requires_discard_dependent_strings ? { discard_dependent_strings: true } : {};
    const result = await engineCommand(item.kind === "refill" ? t("layout.refilling") : t("s7a.deleteField"), async () => {
      try {
        return await (item.kind === "refill" ? engine.updatePvField(pid, item.preview.pv_field_id, item.changes,
          { ...flags, ...(item.preview.requires_discard_manual_layout ? { discard_manual_layout: true } : {}) })
          : engine.deletePvField(pid, item.preview.pv_field_id, flags));
      } catch (error) { captureConflicts(error); throw error; }
    });
    setConfirmation(null);
    if (result) {
      if (item.kind === "refill" || f.fieldId === item.preview.pv_field_id) leaveRefill(result);
      const deletedField = v.bundle.scene.pv_fields.find((field) => field.pv_field_id === item.preview.pv_field_id);
      const roof = deletedField ? fieldSupportIds(deletedField)[0] : undefined;
      toast("ok", `${item.kind === "refill" ? t("layout.refilled") : t("s7a.deleted")} · ${surfaces.find((surface) => surface.surface_id === roof)?.name ?? roofName}`);
    }
  }

  const selTables = tablesOfModules(s.selection, tables).filter((x) => x.status === "active");
  const selModules = s.selection.filter((id) => slotOf(id) && selTables.some((x) => x.table_id === slotOf(id)!.tableId));
  const selLegacy = s.selection.filter((id) => !slotOf(id) && s.modules.some((m) => m.id === id));
  const allPinned = tables.filter((x) => x.pinned);

  return (
    <>
      {confirmation && <ModalDialog label={t(confirmation.kind === "refill" ? "s7a.previewRefill" : "s7a.previewDelete")} onClose={cancel} small alert>
        <header className="modal__head"><h2>{t(confirmation.kind === "refill" ? "s7a.previewRefill" : "s7a.previewDelete")}</h2></header>
        <div className="modal__body">
          <p>{t("rf1.fieldOnRoof", {
            field: v.bundle.scene.pv_fields.find((field) => field.pv_field_id === confirmation.preview.pv_field_id)?.name ?? confirmation.preview.pv_field_id,
            roof: surfaces.find((surface) => v.bundle.scene.pv_fields.some(field => field.pv_field_id === confirmation.preview.pv_field_id && fieldSupportIds(field).includes(surface.surface_id)))?.name ?? roofName
          })}</p>
          {confirmation.kind === "refill" && confirmation.replaces && <p className="note note--warn" data-replaces-layout>{t("layout.replacesLayout")}</p>}
          {confirmation.kind === "refill" && confirmation.moduleChange && <p>{t("rf1.moduleChange", confirmation.moduleChange)}</p>}
          <p>{t("s7a.counts", { before: confirmation.kind === "refill" ? confirmation.preview.module_count_before : confirmation.preview.module_count,
            after: confirmation.kind === "refill" ? confirmation.preview.module_count_after : 0 })}</p>
          <p>{t("s7a.powers", { before: ((confirmation.kind === "refill" ? confirmation.preview.stc_power_w_before : confirmation.preview.stc_power_w) / 1000).toFixed(2),
            after: confirmation.kind === "refill" ? (confirmation.preview.stc_power_w_after / 1000).toFixed(2) : "0.00" })}</p>
          <p>{confirmation.preview.string_ids.length ? t("s7a.strings", { strings: confirmation.preview.string_ids.join(", ") }) : t("s7a.noStrings")}</p>
          {confirmation.kind === "refill" && confirmation.preview.requires_discard_manual_layout && <p className="note note--warn">{t("s7a.manual")}</p>}
          <div className="row">
            <Button tone="danger" disabled={!!s.busy} onClick={() => void confirm()}>{t(confirmation.kind === "refill" ? "s7a.confirmRefill" : "s7a.confirmDelete")}</Button>
            <Button cancel disabled={!!s.busy} onClick={cancel}>{t("s7a.cancel")}</Button>
          </div>
        </div>
      </ModalDialog>}
      <Section primary title={t("layout.fields")}>
        {v.bundle.scene.pv_fields.length === 0 && <div className="empty">{t("layout.noFields")}</div>}
        {v.bundle.scene.pv_fields.map((fl) => {
          if (isExplicitField(fl)) {
            const supports = fieldSupportIds(fl).map(id => surfaces.find(s => s.surface_id === id)?.name ?? id);
            return <div className="card-row" key={fl.pv_field_id}>
              <div><strong>{fl.name}</strong>
                <div className="sub">{t("mesh1.explicit", {tables: fl.tables.length, modules: v.bundle.scene.module_instances.filter(m => m.pv_field_id === fl.pv_field_id).length})}</div>
                <div className="sub">{supports.join(", ") || t("mesh1.freeStanding")}</div>
                <details><summary>{t("mesh1.tableDetails")}</summary>{fl.tables.map(table => {
                  const definition = v.catalog.modules.find(m => m.revision_id === table.module_definition_revision_id);
                  const count = v.bundle.scene.module_instances.filter(m => m.pv_field_id === fl.pv_field_id && m.table_id === table.table_id).length;
                  return <p className="sub" key={table.table_id}>{t("mesh1.tableSummary", {
                    id: table.table_id, module: definition?.model ?? table.module_definition_revision_id,
                    tilt: table.tilt_deg, azimuth: table.azimuth_deg, orientation: table.module_orientation,
                    count, kwp: definition ? (count * moduleNameplateW(definition) / 1000).toFixed(2) : "—",
                    support: table.support_surface_id ? surfaces.find(s => s.surface_id === table.support_surface_id)?.name ?? table.support_surface_id : t("mesh1.freeStanding")
                  })}</p>;
                })}</details>
                <p className="note">{t("mesh1.noRefill")}</p>
              </div>
              <div className="row"><Button small disabled title={t("mesh1.noRefill")}>{t("layout.refill")}</Button>
                <Button small disabled={!!s.busy} onClick={() => void deleteField(fl.pv_field_id)}>{t("s7a.deleteField")}</Button></div>
            </div>;
          }
          const m = v.catalog.modules.find((x) => x.revision_id === fl.module_definition_revision_id);
          const own = tables.filter((x) => x.pv_field_id === fl.pv_field_id);
          const n = own.length ? moduleCountOf(own) : (perField[fl.pv_field_id] ?? 0);
          const req = requests[fl.pv_field_id];
          return (
            // UXF1 (U2-7): name and actions, then one summary line; the rest folds away so narrow panels stay short.
            <div className="card-row card-row--field" key={fl.pv_field_id} data-pv-field-card>
              <strong className="card-row__name" title={fl.name}>{fl.name}</strong>
              <div className="row card-row__actions">
                <Button small disabled={!!s.busy || f.fieldId === fl.pv_field_id || (!req && missingRefillParameters(fl).length > 0)} onClick={() => openRefill(fl)}>
                  {t("layout.refill")}
                </Button>
                <Button small disabled={!!s.busy} onClick={() => void deleteField(fl.pv_field_id)}>{t("s7a.deleteField")}</Button>
              </div>
              <div className="sub card-row__summary">
                {t("layout.fieldSummary", { n, kwp: fmt((n * (m ? moduleNameplateW(m) : 0)) / 1000, 2, "kWp"), tilt: fl.tilt_deg, az: fl.azimuth_deg })}
              </div>
              <details className="card-row__more" open={f.fieldId === fl.pv_field_id}>
                <summary>{t("layout.fieldDetails")}</summary>
                <div className="sub">{t("rf1.roof", { roof: surfaces.find((surface) => surface.surface_id === fl.support_surface_id)?.name ?? fl.support_surface_id })}</div>
                {own.length > 0 && <div className="sub">{t("layout.tableSummary", { tables: own.filter((x) => x.status === "active").length, pinned: own.filter((x) => x.pinned).length })}</div>}
                <span className="tag">{t(`layout.${fl.orientation === "landscape" ? "landscape" : "portrait"}`)}</span>
                {!req && <div className="sub">{t("s7a.legacy")}</div>}
                {!req && missingRefillParameters(fl).length > 0 && <p className="note">{t("s7a.missing", { keys: missingRefillParameters(fl).join(", ") })}</p>}
              </details>
            </div>
          );
        })}

        <h3>{f.fieldId ? t("layout.refillTitle", { name: f.name }) : t("layout.fillZone")}</h3>
        {f.fieldId && (
          <p className="note">
            {t(legacyEditing ? "s7a.refillNote" : "layout.refillNote")}{" "}
            <button type="button" className="linkbtn" onClick={() => leaveRefill()}>
              {t("layout.newFieldInstead")}
            </button>
          </p>
        )}
        <p className="sub">{t("rf1.roof", { roof: roofName })}</p>
        {targetFields.length > 1 && <p className="note">{t("rf1.multipleFields", { roof: roofName, fields: targetFields.map((field) => field.name).join(", ") })}</p>}
        <Field label={t("layout.fieldName")}>
          <input className="input" value={f.name} onChange={(e) => set({ name: e.target.value })} />
        </Field>
        <Field label={t("layout.surface")} hint={draftSurfaces.length ? t("layout.draftSurfaces", { count: draftSurfaces.length }) : undefined}>
          <Select
            value={f.surface}
            onChange={targetRoof}
            options={[
              ...surfaces.map((x) => ({ value: x.surface_id, label: `${x.name} · ${x.surface_type}` })),
              ...draftSurfaces.map((x) => ({ value: x.id, label: `${x.name} (${t("layout.draft")})`, disabled: true }))
            ]}
          />
        </Field>
        <ComponentFilterBar items={v.catalog.modules} filter={modFilter} onChange={setModFilter} showTest={showTest} />
        <Field label={t("layout.module")}>
          <Select value={f.module} onChange={(module) => set({ module })} options={filterComponents(v.catalog.modules, modFilter, showTest, f.module).map((m) => ({ value: m.revision_id, label: componentCatalogLabel(m, `${m.manufacturer} ${m.model} · ${moduleNameplateW(m)} W`, t("s12a.librarySuffix"), t("s12a.layoutOnlySuffix")) }))} />
        </Field>
        {demoModuleChange && <p className="note">{t("rf1.moduleEngineOnly")}</p>}
        {mod && <div className="sub">{t("layout.footprint", { w: mod.width_m.toFixed(3), h: mod.height_m.toFixed(3) })}</div>}

        <FieldGroup label={t("layout.orientation")} hint={t("layout.orientationHint")}>
          <Segmented
            label={t("layout.orientation")}
            value={f.orientation}
            onChange={(orientation) => set({ orientation })}
            options={(["portrait", "landscape"] as const).map((o) => ({
              value: o,
              label: preview ? t("layout.orientationCount", { label: t(`layout.${o}`), n: preview.compare[o] }) : t(`layout.${o}`)
            }))}
          />
        </FieldGroup>

        <h4 className="subhead">{t("layout.mounting")}</h4>
        <FieldGroup label={t("use3.mountingMode")} hint={f.parallel ? t("use3.parallelHint") : undefined}>
          <Segmented<"racks" | "parallel">
            label={t("use3.mountingMode")}
            value={f.parallel ? "parallel" : "racks"}
            onChange={(mode) => set({ parallel: mode === "parallel" })}
            options={[{ value: "racks", label: t("use3.racks") }, { value: "parallel", label: t("use3.parallel") }]}
          />
        </FieldGroup>
        {f.parallel && skew && roofPlane && (
          <div className="issue" role="status" data-edge-misalignment={skew.delta.toFixed(2)}>
            {t("use3b.skew", { delta: skew.delta.toFixed(1), plane: (roofPlane.azimuth_deg ?? 0).toFixed(1), edge: skew.edgeAzimuth.toFixed(1) })}{" "}
            <Button small disabled={!!s.busy} onClick={() => {
              const entity = s.entities.find((e) => e.id === roofPlane.surface_id);
              if (entity) void entitySceneCommand(entity, "edit_plane", { slope_deg: roofPlane.slope_deg, azimuth_deg: Math.round(skew.edgeAzimuth * 1000) / 1000,
                base_elevation_m: roofPlane.base_elevation_m, ...(roofPlane.elevation_reference ? { elevation_reference: roofPlane.elevation_reference } : {}) });
            }}>{t("use3b.alignRoof")}</Button>
          </div>
        )}
        <div className="grid2">
          <Field label={t("layout.tilt")} unit="°" hint={f.parallel ? t("use3.fromRoof") : t("layout.tiltHint")}>
            <NumberInput value={mounting.tilt} step={1} min={0} max={89} disabled={f.parallel} onChange={(tilt) => set({ tilt })} />
          </Field>
          <Field label={t("layout.azimuth")} unit="°" hint={mounting.azimuthFromRoof ? t("use3.fromRoof") : t("layout.azimuthHint")}>
            <NumberInput value={mounting.azimuth} step={1} disabled={mounting.azimuthFromRoof} onChange={(azimuth) => set({ azimuth })} />
          </Field>
          {invalidAzimuth && <p className="note note--bad" role="alert">{t("s7a.azimuth")}</p>}
          <Field label={t("layout.mountingHeight")} unit="m">
            <NumberInput value={f.mount} step={0.05} min={0} onChange={(mount) => set({ mount })} />
          </Field>
        </div>

        <h4 className="subhead">{t("layout.tables")}</h4>
        <div className="grid2">
          <Field label={t("layout.rowsPerTable")}>
            <NumberInput value={f.rows} step={1} min={1} onChange={(rows) => set({ rows })} />
          </Field>
          <Field label={t("layout.moduleGap")} unit="m" hint={t("layout.inPlaneHint")}>
            <NumberInput value={f.gap} step={0.01} min={0} onChange={(gap) => set({ gap })} />
          </Field>
          <Field label={t("layout.inTableGap")} unit="m" hint={t("layout.inPlaneHint")}>
            <NumberInput value={f.inGap} step={0.01} min={0} onChange={(inGap) => set({ inGap })} />
          </Field>
          <Field label={t("layout.leftover")}>
            <Select
              value={f.leftover}
              onChange={(leftover) => set({ leftover })}
              options={[
                { value: "smaller_table", label: t("layout.leftoverSmaller") },
                { value: "smaller_table_front", label: t("layout.leftoverSmallerFront") },
                { value: "leave_empty", label: t("layout.leftoverEmpty") }
              ]}
            />
          </Field>
          <Field label={t("layout.alignment")} hint={t("layout.alignmentHint")}>
            <AlignmentPicker row={f.rowAlign} depth={f.depthAlign} onChange={(rowAlign, depthAlign) => set({ rowAlign, depthAlign })} />
          </Field>
          <Field label={t("layout.sizeCap")} hint={t("layout.zeroNone")}>
            <NumberInput value={f.cap} step={1} min={0} onChange={(cap) => set({ cap })} />
          </Field>
          <Field label={t("layout.walkwayEvery")} hint={t("layout.zeroNone")}>
            <NumberInput value={f.walkEvery} step={1} min={0} onChange={(walkEvery) => set({ walkEvery })} />
          </Field>
          {f.walkEvery > 0 && (
            <Field label={t("layout.walkwayWidth")} unit="m">
              <NumberInput value={f.walkWidth} step={0.05} min={0} onChange={(walkWidth) => set({ walkWidth })} />
            </Field>
          )}
        </div>

        <h4 className="subhead">{t("layout.pitch")}</h4>
        <Segmented
          label={t("layout.pitch")}
          value={f.pitchMode}
          onChange={(pitchMode) => set({ pitchMode })}
          options={[
            { value: "fixed_aisle", label: t("layout.pitchAisle") },
            { value: "gcr", label: t("layout.pitchGcr") },
            { value: "shading_free", label: t("layout.pitchShading") }
          ]}
        />
        <div className="grid2">
          {f.pitchMode === "fixed_aisle" && (
            <Field label={t("layout.aisle")} unit="m" hint={t("layout.onSurfaceHint")}>
              <NumberInput value={f.aisle} step={0.05} min={0} onChange={(aisle) => set({ aisle })} />
            </Field>
          )}
          {f.pitchMode === "gcr" && (
            <Field label={t("layout.gcr")} hint={t("layout.gcrHint")}>
              <NumberInput value={f.gcr} step={0.01} min={0.05} max={1} onChange={(gcr) => set({ gcr })} />
            </Field>
          )}
          {f.pitchMode === "shading_free" && (
            <>
              <Field label={t("layout.sunElevation")} unit="°">
                <NumberInput value={f.sunElevation} step={1} min={1} max={89} onChange={(sunElevation) => set({ sunElevation })} />
              </Field>
              <Field label={t("layout.sunOffset")} unit="°" hint={t("layout.sunOffsetHint")}>
                <NumberInput value={f.sunOffset} step={5} min={-89} max={89} onChange={(sunOffset) => set({ sunOffset })} />
              </Field>
              <p className="sub" role="status" data-shading-free-pitch={sunPitch ? sunPitch.row_pitch_m.toFixed(3) : ""}>
                {sunPitch ? t("use1.sunPitch", { pitch: fmt(sunPitch.row_pitch_m, 2, "m"), gcr: sunPitch.ground_coverage_ratio.toFixed(2) }) : t("use1.sunPitchPending")}
              </p>
            </>
          )}
        </div>
        {preview && preview.pitch_m > 0 && <p className="note">{t("layout.pitchResult", { pitch: preview.pitch_m.toFixed(3) })}</p>}
        {f.tilt > 0 && f.pitchMode !== "shading_free" && (
          <p className="note">
            <GlyphInfo className="glyph glyph--info" /> {t("layout.geometricOnly")}
          </p>
        )}

        <h4 className="subhead">{t("layout.setbacks")}</h4>
        <Check checked={f.sameSetback} onChange={(sameSetback) => set({ sameSetback, edgeSetbacks: edges.map(() => f.setback) })} label={t("layout.sameSetback")} />
        {f.sameSetback ? (
          <Field label={t("layout.edgeSetback")} unit="m">
            <NumberInput value={f.setback} step={0.05} min={0} onChange={(setback) => set({ setback })} />
          </Field>
        ) : (
          <div className="grid2">
            {edges.map((p, i) => {
              const q = edges[(i + 1) % edges.length];
              return (
                <Field key={i} label={t("layout.edgeN", { n: i + 1, len: Math.hypot(q[0] - p[0], q[1] - p[1]).toFixed(2), facing: edgeFacing(edges, i).toFixed(0) })} unit="m">
                  <NumberInput
                    value={f.edgeSetbacks[i] ?? f.setback}
                    step={0.05}
                    min={0}
                    onChange={(x) => set({ edgeSetbacks: edges.map((_, k) => (k === i ? x : (f.edgeSetbacks[k] ?? f.setback))) })}
                  />
                </Field>
              );
            })}
          </div>
        )}
        <Field label={t("layout.keepout")} unit="m" hint={t("layout.keepoutHint")}>
          <NumberInput value={f.keepout} step={0.05} min={0} onChange={(keepout) => set({ keepout })} />
        </Field>

        {occupied && <div className="note" data-occupied-roof>
          <p>{t("layout.occupiedReplace", { roof: roofName, field: occupied.name })}</p>
          {isExplicitField(occupied) && <p>{t("mesh1.noRefill")}</p>}
          {!!occupiedMapping?.reasons.length && <p className="note note--bad">{t("layout.needsProposal", { reasons: occupiedMapping.reasons.join(", ") })}</p>}
        </div>}
        {legacyEditing && <div className="preview-box" aria-live="polite">
          <p>{t("s7a.refillNote")}</p>
          {mapped?.reasons.length ? <p className="note note--bad">{t("layout.needsProposal", { reasons: mapped.reasons.join(", ") })}</p> :
            !Object.keys(mapped?.changes ?? {}).length && <p>{t("s7a.unchanged")}</p>}
          {conflicts.length > 0 && <div role="alert"><strong>{t("s7a.conflicts")}</strong><ul>{conflicts.map((c, i) =>
            <li key={i}>{[c.module_instance_id, c.pv_field_id, c.other_pv_field_id, c.other_id].filter(Boolean).map(String).join(" · ")}</li>)}</ul></div>}
        </div>}
        {!legacyEditing && <div className="preview-box" aria-live="polite">
          {preview && (
            <>
              <div>
                <strong>{t("layout.previewCount", { n: preview.module_count, tables: preview.tables.filter((x) => x.status === "active").length })}</strong>
                <span className="sub"> · {t("layout.previewNotApplied")}</span>
              </div>
              {f.fieldId && (
                <div className="sub">
                  {t("layout.diff", {
                    before: preview.diff.modules_before,
                    after: preview.diff.modules_after,
                    added: preview.diff.tables_added,
                    removed: preview.diff.tables_removed,
                    same: preview.diff.tables_unchanged,
                    pinned: preview.diff.tables_pinned_kept
                  })}
                </div>
              )}
              {preview.diff.strings_affected.length > 0 && (
                <p className="note note--warn">
                  <GlyphWarning className="glyph glyph--warning" /> {t("layout.stringsAffected", { list: preview.diff.strings_affected.join(", ") })}
                </p>
              )}
              {preview.findings.map((x) => (
                <p key={x.code} className={x.severity === "blocking" ? "note note--bad" : "note note--warn"}>
                  {x.severity === "blocking" ? <GlyphBlocked className="glyph glyph--blocked" /> : <GlyphWarning className="glyph glyph--warning" />} {x.message}
                </p>
              ))}
            </>
          )}
          {!preview && previewState === "loading" && <div className="sub">{t("layout.previewing")}</div>}
          {!preview && previewState === "error" && (
            <p className="note note--bad">
              <GlyphBlocked className="glyph glyph--blocked" /> {previewError}
            </p>
          )}
          {!preview && previewState === "unavailable" && (
            <div className="sub">
              {t("layout.previewUnavailable")} <NotWired id="fillPreview" compact />
              {legacy.input ? (
                <div>{t("layout.legacyRoute")}</div>
              ) : (
                <div>
                  {t("layout.needsProposal", { reasons: legacy.reasons.join(", ") })} <NotWired id="fillApply" compact />
                </div>
              )}
            </div>
          )}
        </div>}
        <div className="row">
          <Button tone="primary" disabled={!canApply} onClick={() => void apply()}>
            {f.fieldId ? t("layout.applyRefill") : t("layout.apply")}
          </Button>
          {preview && (
            <Button small onClick={() => dispatch({ type: "setLayoutPreview", preview: null })}>
              {t("layout.hidePreview")}
            </Button>
          )}
        </div>
        <p className="sub">{t("layout.oneUndo")}</p>
      </Section>

      <Section primary={s.selection.length > 0} title={t("sections.selection")}>
        {selTables.length === 0 && selLegacy.length === 0 && <div className="empty">{t("layout.selectHint")}</div>}
        {selTables.length > 0 && (
          <>
            <div className="sub">
              {t("layout.selected", { modules: selModules.length, tables: selTables.length, pinned: selTables.filter((x) => x.pinned).length })}
            </div>
            <div className="row wrap">
              <Button small disabled={!!s.busy} onClick={() => void edits.deleteModules(selModules)}>
                {t("layout.deleteModules")}
              </Button>
              <Button small disabled={!!s.busy} onClick={() => void edits.deleteTables(selTables.map((x) => x.table_id))}>
                {t("layout.deleteTables")}
              </Button>
              <Button small disabled={!!s.busy || !selTables.some((x) => x.pinned)} onClick={() => void edits.unpinTables(selTables.filter((x) => x.pinned).map((x) => x.table_id))}>
                {t("layout.unpin")}
              </Button>
            </div>
            <div className="grid2">
              <Field label={t("layout.moveDx")} unit="m">
                <NumberInput value={move[0]} step={0.1} onChange={(x) => setMove([x, move[1]])} />
              </Field>
              <Field label={t("layout.moveDy")} unit="m">
                <NumberInput value={move[1]} step={0.1} onChange={(y) => setMove([move[0], y])} />
              </Field>
            </div>
            <Button small disabled={!!s.busy} onClick={() => void edits.moveTables(selTables.map((x) => x.table_id), move)}>
              {t("layout.moveTables")}
            </Button>
            <p className="sub">{t("layout.pinNote")}</p>
          </>
        )}
        {selLegacy.length > 0 && (
          <p className="note">
            {t("layout.legacyModules", { count: selLegacy.length })} <NotWired id="moduleEdit" compact />
          </p>
        )}
        {allPinned.length > 0 && selTables.length === 0 && <div className="sub">{t("layout.pinnedCount", { count: allPinned.length })}</div>}
      </Section>
    </>
  );
}

/** UXF1 (U2-6): nine anchor points. Top row = the front (low) edge, bottom = the back (high) edge, as seen with the
 *  modules facing up the page. Columns run along the rows. Each cell sets both directions. */
const DEPTHS: Alignment[] = ["end", "center", "start"];
const ROWS: Alignment[] = ["start", "center", "end"];
export function AlignmentPicker({ row, depth, onChange }: { row: Alignment; depth: Alignment | null; onChange: (row: Alignment, depth: Alignment) => void }) {
  const { t } = useTranslation();
  const depthName = { end: t("layout.alignFront"), center: t("layout.alignMiddle"), start: t("layout.alignBack") };
  const rowName = { start: t("layout.alignLeft"), center: t("layout.alignCentre"), end: t("layout.alignRight") };
  return (
    <div className="align-picker" role="group" aria-label={t("layout.alignment")} data-align-picker>
      <span className="align-picker__edge">{t("layout.alignFrontEdge")}</span>
      <div className="align-picker__grid">
        {DEPTHS.flatMap((d) => ROWS.map((r) => (
          <button key={`${d}-${r}`} type="button" className="align-picker__cell" aria-pressed={depth === d && row === r}
            aria-label={`${depthName[d]} ${rowName[r]}`} title={`${depthName[d]} ${rowName[r]}`} onClick={() => onChange(r, d)} />
        )))}
      </div>
      <span className="align-picker__edge">{t("layout.alignBackEdge")}</span>
      {depth === null && <span className="align-picker__note">{t("layout.alignAuto")}</span>}
    </div>
  );
}
