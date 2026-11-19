import { modulePlacement, isExplicitField, moduleNameplateW } from "./types";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { DEMO, engine } from "./client";
import { useEntityEdits } from "./canvas/useEntityEdits";
import { useModuleEdits } from "./canvas/useModuleEdits";
import { tablesOfModules } from "./canvas/useTableEdits";
import { area, bounds, centroid, perimeter, planeZ, PlaneDef, referenceEdgePlane, validatePolygon, Vec2, vertexLabel } from "./geometry";
import { Entity, useActions, useUI } from "./state/store";
import { Button, Field, fmt, Kv, NotWired, NumberInput, Section, Select } from "./ui/kit";
import { engineCommand, redo, undo } from "./state/history";
import { ownBox, isRectangle } from "./canvas/plan/edit";
import { AlignmentPicker } from "./panels/LayoutPanel";
import { Trash } from "./ui/icons";


function shortHash(v: string) {
  return v.length <= 14 ? v : `${v.slice(0, 8)}…${v.slice(-6)}`;
}


export function Inspector() {
  const { t } = useTranslation();
  const state = useUI((s) => ({ entities: s.entities, modules: s.modules, selection: s.selection, view: s.view, busy: s.busy }));
  const { dispatch } = useActions();
  const moduleEdits = useModuleEdits();
  const selected = useMemo(() => new Set(state.selection), [state.selection]);
  const moduleIds = useMemo(() => new Set(state.modules.map((m) => m.id)), [state.modules]);
  const ent = state.entities.find((e) => selected.has(e.id));
  const mod = !ent ? state.modules.find((m) => selected.has(m.id)) : undefined;
  const sceneItems = state.entities.filter((e) => selected.has(e.id));
  const deleteTargets = sceneItems.filter((e) => !e.locked);
  const moduleItems = state.modules.filter((m) => selected.has(m.id));
  const multiple = sceneItems.length + moduleItems.length > 1;
  const powerW = moduleItems.reduce((sum, m) => {
    const placement = state.view ? modulePlacement(state.view, m.id) : undefined;
    const definition = state.view?.catalog.modules.find((d) => d.revision_id === placement?.revisionId);
    return sum + (definition ? moduleNameplateW(definition) : 0);
  }, 0);
  const summary = multiple ? <Section primary title={t("s13a.selection")}>
    {([ ["surface", "roofs"], ["obstacle", "obstacles"], ["keepout", "keepouts"] ] as const).map(([kind, key]) =>
      <p key={kind}>{t(`s13a.${key}`, { count: sceneItems.filter((e) => e.kind === kind).length })}</p>)}
    <p>{t("s13a.modules", { count: moduleItems.length })}</p>
    <p>{t("s13a.power", { kwp: (powerW / 1000).toFixed(2) })}</p>
    <div className="row">
      <Button small onClick={() => dispatch({ type: "select", ids: [] })}>{t("s13a.clear")}</Button>
      {!moduleItems.length && <Button small tone="danger" disabled={!!state.busy || !deleteTargets.length}
        title={!deleteTargets.length ? t("s13a.lockedCount", { count: sceneItems.length }) : undefined} onClick={() =>
        window.dispatchEvent(new CustomEvent("rawibumi:delete-request", { detail: deleteTargets.map((e) => e.id) }))
      }>{t("s13a.delete", { count: deleteTargets.length })}</Button>}
    </div>
  </Section> : null;
  if (multiple && ent) return <div className="inspector">{summary}</div>;
  if (ent) return <EntityInspector e={ent} />;
  if (mod) {
    const v = state.view!;
    const field = v.bundle.scene.pv_fields.find((f) => f.pv_field_id === mod.fieldId);
    const placement = modulePlacement(v, mod.id);
    const readOnly = moduleItems.some(m => { const p = modulePlacement(v, m.id); return p && isExplicitField(p.field); });
    const count = state.selection.filter((id) => moduleIds.has(id)).length;
    const inTables = tablesOfModules(state.selection, v.table_layout?.tables ?? []).some((table) => table.status === "active");
    return (
      <div className="inspector">
        {summary}
        <Section primary title={count > 1 ? t("hardening.modules", { count }) : t("hardening.module")}>
          <Kv
            rows={[
              ["Instance", mod.id],
              ["PV field", field?.name ?? mod.fieldId],
              ["Tilt / azimuth", placement ? `${placement.tiltDeg}° / ${placement.azimuthDeg}°` : "—"],
              ["String", mod.stringId ?? "unstrung"],
              ["MPPT", mod.mpptKey ? `${mod.mpptKey.split("#")[0]} · MPPT ${Number(mod.mpptKey.split("#")[1]) + 1}` : "unassigned"]
            ]}
          />
          <p className="note">
            {t(readOnly ? "mesh1.noRefill" : inTables ? "s13b.tableNote" : "s13b.moveNote")} <NotWired id="moduleEdit" compact />
          </p>
          <Button small tone="danger" disabled={!!state.busy || inTables || readOnly} title={readOnly ? t("mesh1.noRefill") : inTables ? t("s13b.tableNote") : undefined}
            onClick={() => void moduleEdits.previewDelete(state.selection.filter((id) => moduleIds.has(id)))}>
            {t("s13b.delete", { count })}
          </Button>
        </Section>
      </div>
    );
  }
  return <ProjectInspector />;
}


function ProjectInspector() {
  const { t } = useTranslation();
  const state = useUI((s) => ({ view: s.view, busy: s.busy, undoDepth: s.past.length, redoDepth: s.future.length }));
  const v = state.view!;
  return (
    <div className="inspector">
      <Section title="Topology">
        {v.topology_view.inverters.map((inv) => (
          <div className="tree" key={inv.inverter_instance_id}>
            <strong>{inv.name}</strong>
            {inv.mppts.map((m) => (
              <div className="tree__row" key={m.mppt_instance_id}>
                MPPT {m.index} · {m.strings.length ? m.strings.map((s) => `${s.name}(${s.module_count})`).join(" ") : "—"}
              </div>
            ))}
          </div>
        ))}
        {v.topology_view.unassigned_strings.length > 0 && <div className="issue issue--draft">{v.topology_view.unassigned_strings.length} strings await MPPT assignment.</div>}
      </Section>
      <Section title={t("history.title")}>
        <div className="row">
          <Button small onClick={() => void undo()} disabled={!state.busy && !state.undoDepth}>
            {t("history.undo", { n: state.undoDepth })}
          </Button>
          <Button small onClick={() => void redo()} disabled={!!state.busy || !state.redoDepth}>
            {t("history.redo", { n: state.redoDepth })}
          </Button>
        </div>
        <p className="note">{DEMO ? t("history.noteDemo") : t("history.noteHttp", { limit: v.history?.limit ?? 10 })}</p>
      </Section>
      <Section title="Canonical identity">
        <Kv
          rows={[
            ["Project revision", String(v.bundle.project.project_revision.revision_number)],
            ["Scene hash", <span key="s" title={v.identity.scene_hash}>{shortHash(v.identity.scene_hash)}</span>],
            ["Electrical hash", <span key="e" title={v.identity.electrical_hash}>{shortHash(v.identity.electrical_hash)}</span>]
          ]}
        />
      </Section>
    </div>
  );
}


function EntityInspector({ e }: { e: Entity }) {
  const { t } = useTranslation();
  const state = useUI((s) => ({ view: s.view, busy: s.busy, vertex: s.vertex }));
  const { dispatch, toast } = useActions();
  const v = state.view!;
  const [ownAxes, setOwnAxes] = useState(false);
  const [dx, setDx] = useState(1);
  const [dy, setDy] = useState(0);
  const [rot, setRot] = useState(15);
  const [scale, setScale] = useState(100);
  const edits = useEntityEdits();
  const anchor = (e as Entity & { reference_anchor?: import("./types").ReferenceAnchor }).reference_anchor
    ?? (v.bundle.scene.surfaces?.find(s => s.surface_id === e.id) ?? v.bundle.scene.obstacles?.find(o => o.obstacle_id === e.id))?.reference_anchor
    ?? { u: "start", v: "start" };
  const box = ownBox(e.polygon, anchor);
  const blocked = !!state.busy || e.locked || (e.source === "engine" && e.modified);
  const draftBlocked = e.source === "engine" && e.modified;


  const update = (patch: Partial<Entity>, pendingId?: string) =>
    dispatch({
      type: "updateEntity",
      id: e.id,
      patch: {
        ...patch,
        modified: e.source === "engine" && pendingId ? true : e.modified,
        pending: pendingId && e.source === "engine" ? [...new Set([...e.pending, pendingId])] : e.pending
      }
    });


  const applyGeometry = (polygon: Vec2[], holes: Vec2[][], pendingId: string) => {
    const issues = validatePolygon(polygon);
    if (issues.length) return toast("error", `Rejected: ${issues[0].message}`);
    update({ polygon, holes }, pendingId);
  };


  const plane = e.plane;
  const setPlane = (p: PlaneDef) => void edits.editPlane(e, p);


  return (
    <div className="inspector">
      <Section primary title={e.name}>
        <div className="badges">
          <span className="tag">{e.kind}</span>
          <span className={e.source === "draft" ? "tag tag--draft" : e.modified ? "tag tag--draft" : "tag tag--ok"}>
            {e.source === "draft" ? "local draft" : e.modified ? "engine + local edits" : "engine"}
          </span>
          {e.hostsPvField && <span className="tag">hosts PV field</span>}
        </div>
        {e.pending.length > 0 && (
          <div className="pending-list">
            To commit: {e.pending.map((p) => <NotWired key={p} id={p} compact />)} <span className="sub">{e.pending.join(", ")}</span>
          </div>
        )}
        {draftBlocked && <Button small onClick={() => dispatch({ type: "discardEntityDraft", id: e.id })}>Discard draft</Button>}
        <Field label="Name">
          <input key={`${e.id}:${e.name}`} className="input" defaultValue={e.name}
            onBlur={(ev) => { if (ev.target.value !== e.name) dispatch({ type: "updateEntity", id: e.id, patch: { name: ev.target.value } }); }}
            onKeyDown={(ev) => { if (ev.key === "Enter") ev.currentTarget.blur(); }} />
        </Field>
        <Kv
          rows={[
            ["Area", `${area(e.polygon, e.holes).toFixed(2)} m²`],
            ["Perimeter", `${perimeter(e.polygon).toFixed(2)} m`],
            ["Vertices", `${e.polygon.length}${e.holes.length ? ` + ${e.holes.length} hole(s)` : ""}`]
          ]}
        />
      </Section>


      <Section primary title="Transform">
        <fieldset disabled={blocked}>
          <legend>{t("bld1.reference")}</legend>
          <AlignmentPicker row={anchor.u} depth={anchor.v} onChange={(u, v) => void edits.setReferenceAnchor(e, { u, v })} />
          <div className="grid2">
            <Field label={t("bld1.positionX")} unit="m"><NumberInput value={box.point[0]} commit onChange={x => void edits.setPosition(e, 0, x)} /></Field>
            <Field label={t("bld1.positionY")} unit="m"><NumberInput value={box.point[1]} commit onChange={y => void edits.setPosition(e, 1, y)} /></Field>
          </div>
          <Button small onClick={() => void edits.commitMove(e, [-box.point[0], -box.point[1]])}>{t("bld1.toOrigin")}</Button>
          <Field label={t("bld1.orientation")} unit="°"><NumberInput value={Number(box.bearing.toFixed(1))} step={0.1} commit onChange={a => void edits.setOrientation(e, a)} /></Field>
          {isRectangle(e.polygon) && <div className="grid2">
            <Field label={t("bld1.length")} unit="m"><NumberInput value={box.length} min={0.001} commit onChange={n => void edits.editDimension(e, 0, n)} /></Field>
            <Field label={t("bld1.width")} unit="m"><NumberInput value={box.width} min={0.001} commit onChange={n => void edits.editDimension(e, 1, n)} /></Field>
          </div>}
          <Field label={t("bld1.moveBy")}><Select value={ownAxes ? "own" : "scene"} onChange={s => setOwnAxes(s === "own")} options={[{ value: "scene", label: t("bld1.sceneAxes") }, { value: "own", label: t("bld1.ownAxes") }]} /></Field>
        </fieldset>
        <div className="grid3">
          <Field label="ΔX" unit="m">
            <NumberInput value={dx} onChange={setDx} />
          </Field>
          <Field label="ΔY" unit="m">
            <NumberInput value={dy} onChange={setDy} />
          </Field>
          <Field label=" ">
            <Button
              small
              disabled={!!state.busy || e.locked || draftBlocked}
              title={draftBlocked ? "Discard the local draft edits first" : undefined}
              onClick={() => void edits.moveBy(e, [dx, dy], ownAxes)}
            >
              Move
            </Button>
          </Field>
          <Field label="Rotate" unit="° clockwise">
            <NumberInput value={rot} step={1} onChange={setRot} />
          </Field>
          <Field label=" ">
            <Button
              small
              disabled={!!state.busy || e.locked || draftBlocked}
              title={draftBlocked ? "Discard the local draft edits first" : undefined}
              onClick={() => {
                // As the engine's rotate: clockwise positive, about the bounding-box centre.
                const b = bounds([e.polygon]);
                const c: Vec2 = [(b.minX + b.maxX) / 2, (b.minY + b.maxY) / 2];
                void edits.rotate(e, c, rot);
              }}
            >
              {t("bld1.rotateCentre")}
            </Button>
          </Field>
          <Button small disabled={blocked} onClick={() => void edits.rotate(e, box.point, rot)}>{t("bld1.rotateReference")}</Button>
          <Field label="Resize" unit="%">
            <NumberInput value={scale} step={1} min={1} onChange={setScale} />
          </Field>
          <Field label=" ">
            <Button
              small
              disabled={!!state.busy || e.locked || draftBlocked}
              onClick={() => {
                const b = bounds([e.polygon]);
                const c: Vec2 = [(b.minX + b.maxX) / 2, (b.minY + b.maxY) / 2];
                const k = scale / 100;
                void edits.resize(e, c, k);
              }}
            >
              Resize
            </Button>
          </Field>
        </div>
        <p className="note">{draftBlocked ? "Discard the local draft edits first" : t("s9.engineEdits")}</p>
      </Section>


      {e.kind !== "keepout" && (
        <Section primary title={e.kind === "surface" ? "Plane and heights" : "Heights"}>
          {e.kind === "obstacle" ? (
            <div className="grid2">
              <Field label={t("plane.baseHeight")} unit="m">
                <NumberInput value={plane.mode === "flat" ? plane.z_m : 0} disabled={!!state.busy || draftBlocked} commit onChange={(z) => void edits.setBaseElevation(e, z)} />
              </Field>
              <Field label={t("plane.height")} unit="m">
                <NumberInput value={e.height_m} min={0} max={1000} disabled={!!state.busy || draftBlocked || e.locked} commit onChange={(h) => void edits.editHeight(e, h)} />
              </Field>
            </div>
          ) : (
            <>
              <Field label={t("plane.definition")}>
                <Select
                  disabled={!!state.busy || draftBlocked || e.locked}
                  value={plane.mode}
                  onChange={(mode) => {
                    if (mode === "flat") setPlane({ mode: "flat", z_m: plane.mode === "flat" ? plane.z_m : 0 });
                    if (mode === "edge_tilt") setPlane(referenceEdgePlane(plane, 0));
                    if (mode === "datum_tilt_azimuth") setPlane({ mode: "datum_tilt_azimuth", datum: centroid(e.polygon), z_m: 8, tilt_deg: 5, slopeAzimuth_deg: 180 });
                  }}
                  options={[
                    { value: "flat", label: t("plane.flatMode") },
                    { value: "edge_tilt", label: t("plane.edgeMode") },
                    { value: "datum_tilt_azimuth", label: t("plane.heightMode") }
                  ]}
                />
              </Field>
              {plane.mode === "flat" && (
                <Field label={t("plane.roofHeight")} unit="m">
                  <NumberInput value={plane.z_m} disabled={!!state.busy || draftBlocked} commit onChange={(z) => void edits.setBaseElevation(e, z)} />
                </Field>
              )}
              {plane.mode === "edge_tilt" && (
                <div className="grid2">
                  <Field label={t("plane.referenceEdge")}>
                    <div className="row">
                      <Select
                        disabled={!!state.busy || draftBlocked || e.locked}
                        value={String(plane.edgeIndex)}
                        onChange={(s) => setPlane({ ...plane, edgeIndex: Number(s) })}
                        options={e.polygon.map((_, i) => ({ value: String(i), label: `${label(i)}${label((i + 1) % e.polygon.length)}` }))}
                      />
                      <Button small disabled={!!state.busy || draftBlocked || e.locked} onClick={() => window.dispatchEvent(new CustomEvent("rawibumi:pick-reference-edge", { detail: e.id }))}>
                        {t("ux2.pickOnPlan")}
                      </Button>
                    </div>
                  </Field>
                  <Field label={t("plane.edgeHeight")} unit="m">
                    <NumberInput disabled={!!state.busy || draftBlocked || e.locked} value={plane.zRef_m} onChange={(z) => setPlane({ ...plane, zRef_m: z })} />
                  </Field>
                  <Field label={t("plane.tilt")} unit="°">
                    <NumberInput disabled={!!state.busy || draftBlocked || e.locked} value={plane.tilt_deg} step={0.5} min={0} max={80} onChange={(t) => setPlane({ ...plane, tilt_deg: t })} />
                  </Field>
                  <Field label={t("plane.slope")}>
                    <Select
                      disabled={!!state.busy || draftBlocked || e.locked}
                      value={plane.direction}
                      onChange={(direction) => setPlane({ ...plane, direction })}
                      options={[
                        { value: "down", label: t("plane.falls") },
                        { value: "up", label: t("plane.rises") }
                      ]}
                    />
                  </Field>
                </div>
              )}
              {plane.mode === "datum_tilt_azimuth" && (
                <div className="grid2">
                  <Field label={t("plane.referenceHeight")} unit="m">
                    <NumberInput disabled={!!state.busy || draftBlocked || e.locked} value={plane.z_m} onChange={(z) => setPlane({ ...plane, z_m: z })} />
                  </Field>
                  <Field label={t("plane.tilt")} unit="°">
                    <NumberInput disabled={!!state.busy || draftBlocked || e.locked} value={plane.tilt_deg} step={0.5} onChange={(t) => setPlane({ ...plane, tilt_deg: t })} />
                  </Field>
                  <Field label={t("plane.downslope")} unit={t("plane.downslopeUnit")}>
                    <NumberInput disabled={!!state.busy || draftBlocked || e.locked} value={plane.slopeAzimuth_deg} step={1} onChange={(a) => setPlane({ ...plane, slopeAzimuth_deg: a })} />
                  </Field>
                </div>
              )}
              <table className="tbl tbl--dense">
                <thead>
                  <tr>
                    <th>Vertex</th>
                    <th className="num">X (m)</th>
                    <th className="num">Y (m)</th>
                    <th className="num">Z (m)</th>
                    <th>Z source</th>
                    <th><span className="visually-hidden">{t("ux3.vertexActions")}</span></th>
                  </tr>
                </thead>
                <tbody>
                  {e.polygon.map((p, i) => {
                    const z = planeZ(e.polygon, plane, p);
                    const isRef = plane.mode === "edge_tilt" && (i === plane.edgeIndex || i === (plane.edgeIndex + 1) % e.polygon.length);
                    const chosen = state.vertex?.id === e.id && state.vertex.ring === 0 && state.vertex.index === i;
                    // UX3: the same delete as the plan's Delete key; disabled with its reason.
                    const deleteBlock = e.locked ? t("tools.locked", { name: e.name }) : draftBlocked ? t("s7b.discardReason")
                      : state.busy ? t("commands.running") : e.polygon.length <= 3 ? t("ux2.minVertices") : undefined;
                    return (
                      <tr key={i} className={chosen ? "tbl__row--selected" : undefined} aria-selected={chosen} data-vertex-row={i}
                        onClick={() => dispatch({ type: "setVertex", vertex: { id: e.id, ring: 0, index: i } })}>
                        <td>{label(i)}</td>
                        <td className="num">{f3(p[0])}</td>
                        <td className="num">{f3(p[1])}</td>
                        <td className="num">{z == null ? "—" : f3(z)}</td>
                        <td className="sub">{plane.mode === "flat" ? "plane" : isRef ? "reference" : "derived (preview)"}</td>
                        <td>
                          <button type="button" className="iconbtn" aria-label={t("ux3.deleteVertex", { vertex: label(i) })}
                            title={deleteBlock ?? t("ux3.deleteVertex", { vertex: label(i) })} aria-disabled={deleteBlock ? true : undefined}
                            onClick={(ev) => { ev.stopPropagation(); if (deleteBlock) return; dispatch({ type: "setVertex", vertex: null }); void edits.deleteVertex(e, i, 0); }}>
                            <Trash />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <p className="note">
                {t("s11b.planeAuthority")}
              </p>
            </>
          )}

        </Section>
      )}


      <Section title="Danger zone" defaultOpen={false}>
        <Button tone="danger" small disabled={!!state.busy || e.locked} onClick={() => window.dispatchEvent(new CustomEvent("rawibumi:delete-request", { detail: e.id }))}>
          Delete {e.kind}
        </Button>
      </Section>
    </div>
  );
}


const label = vertexLabel;


function f3(v: number) {
  return (Math.abs(v) < 5e-4 ? 0 : v).toFixed(3);
}
