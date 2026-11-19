import { useState } from "react";
import { engine } from "./client";
import { area, centroid, perimeter, planeZ, PlaneDef, rotatePoly, scalePoly, validatePolygon, Vec2 } from "./geometry";
import { Entity, useStore } from "./state/store";
import { Button, Field, fmt, Kv, NotWired, NumberInput, Section, Select } from "./ui/kit";


function shortHash(v: string) {
  return v.length <= 14 ? v : `${v.slice(0, 8)}…${v.slice(-6)}`;
}


export function Inspector() {
  const { state } = useStore();
  const ent = state.entities.find((e) => state.selection.includes(e.id));
  const mod = !ent ? state.modules.find((m) => state.selection.includes(m.id)) : undefined;
  if (ent) return <EntityInspector e={ent} />;
  if (mod) {
    const v = state.view!;
    const field = v.bundle.scene.pv_fields.find((f) => f.pv_field_id === mod.fieldId);
    const count = state.selection.filter((id) => state.modules.some((m) => m.id === id)).length;
    return (
      <div className="inspector">
        <Section title={count > 1 ? `${count} modules` : "Module"}>
          <Kv
            rows={[
              ["Instance", mod.id],
              ["PV field", field?.name ?? mod.fieldId],
              ["Tilt / azimuth", field ? `${field.tilt_deg}° / ${field.azimuth_deg}°` : "—"],
              ["String", mod.stringId ?? "unstrung"],
              ["MPPT", mod.mpptKey ? `${mod.mpptKey.split("#")[0]} · MPPT ${Number(mod.mpptKey.split("#")[1]) + 1}` : "unassigned"]
            ]}
          />
          <p className="note">
            Module footprints come from the component revision and cannot be resized. Individual edits: <NotWired id="moduleEdit" compact />
          </p>
        </Section>
      </div>
    );
  }
  return <ProjectInspector />;
}


function ProjectInspector() {
  const { state, dispatch } = useStore();
  const v = state.view!;
  const kwp = state.modules.reduce((t, m) => {
    const f = v.bundle.scene.pv_fields.find((x) => x.pv_field_id === m.fieldId);
    const md = v.catalog.modules.find((x) => x.revision_id === f?.module_definition_revision_id);
    return t + (md?.pmp_w ?? 0) / 1000;
  }, 0);
  const acKw = v.bundle.electrical_design.inverter_instances.reduce((t, i) => {
    const d = v.catalog.inverters.find((x) => x.revision_id === i.inverter_definition_revision_id);
    return t + (d?.nominal_ac_power_w ?? 0) / 1000;
  }, 0);
  return (
    <div className="inspector">
      <div className="metrics">
        <div>
          <span>Modules</span>
          <strong>{state.modules.length.toLocaleString()}</strong>
        </div>
        <div>
          <span>DC capacity</span>
          <strong>{fmt(kwp, 2)}</strong>
          <em>kWp</em>
        </div>
        <div>
          <span>AC capacity</span>
          <strong>{fmt(acKw, 1)}</strong>
          <em>kW</em>
        </div>
        <div>
          <span>DC/AC</span>
          <strong>{acKw ? (kwp / acKw).toFixed(2) : "—"}</strong>
        </div>
      </div>
      <p className="note">DC capacity uses catalog Pmp. The engine should confirm whether that equals nameplate PNom.</p>
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
      <Section title="History" aside={<NotWired id="undoRedo" compact />}>
        <div className="row">
          <Button small onClick={() => dispatch({ type: "undo" })} disabled={!state.past.length}>
            Undo ({state.past.length})
          </Button>
          <Button small onClick={() => dispatch({ type: "redo" })} disabled={!state.future.length}>
            Redo ({state.future.length})
          </Button>
        </div>
        <p className="note">Local draft history. Engine commands already applied are not reverted by local undo until the engine endpoint is wired.</p>
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
  const { state, dispatch, run, toast } = useStore();
  const v = state.view!;
  const [dx, setDx] = useState(1);
  const [dy, setDy] = useState(0);
  const [rot, setRot] = useState(15);
  const [scale, setScale] = useState(100);
  const isEngineClean = e.source === "engine" && !e.modified;


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
  const setPlane = (p: PlaneDef) => update({ plane: p }, "planeDefinition");


  return (
    <div className="inspector">
      <Section title={e.name}>
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
        <Field label="Name">
          <input className="input" value={e.name} onChange={(ev) => dispatch({ type: "updateEntity", id: e.id, patch: { name: ev.target.value }, history: false })} />
        </Field>
        <Kv
          rows={[
            ["Area", `${area(e.polygon, e.holes).toFixed(2)} m²`],
            ["Perimeter", `${perimeter(e.polygon).toFixed(2)} m`],
            ["Vertices", `${e.polygon.length}${e.holes.length ? ` + ${e.holes.length} hole(s)` : ""}`]
          ]}
        />
      </Section>


      <Section title="Transform">
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
              disabled={e.locked}
              onClick={async () => {
                if (isEngineClean) {
                  const r = await run("Moving", () => engine.moveSceneEntity(v.bundle.project.project_id, { entity_id: e.id, dx_m: dx, dy_m: dy }));
                  if (r) {
                    dispatch({ type: "checkpoint" });
                    dispatch({ type: "setView", view: r });
                  }
                } else applyGeometry(e.polygon.map(([x, y]) => [x + dx, y + dy]), e.holes.map((h) => h.map(([x, y]) => [x + dx, y + dy])), "editVertices");
              }}
            >
              Move
            </Button>
          </Field>
          <Field label="Rotate" unit="° ccw">
            <NumberInput value={rot} step={1} onChange={setRot} />
          </Field>
          <Field label=" ">
            <Button
              small
              disabled={e.locked}
              onClick={() => {
                const c = centroid(e.polygon);
                applyGeometry(rotatePoly(e.polygon, c, rot), e.holes.map((h) => rotatePoly(h, c, rot)), "rotateEntity");
              }}
            >
              Rotate
            </Button>
          </Field>
          <span />
          <Field label="Resize" unit="%">
            <NumberInput value={scale} step={1} min={1} onChange={setScale} />
          </Field>
          <Field label=" ">
            <Button
              small
              disabled={e.locked}
              onClick={() => {
                const c = centroid(e.polygon);
                const k = scale / 100;
                applyGeometry(scalePoly(e.polygon, c, k), e.holes.map((h) => scalePoly(h, c, k)), "scaleEntity");
              }}
            >
              Resize
            </Button>
          </Field>
        </div>
        <p className="note">{isEngineClean ? "Move is committed by the engine. Rotate and resize stay local until their endpoints exist." : "Edits stay local until the endpoints exist."}</p>
      </Section>


      {e.kind !== "keepout" && (
        <Section title={e.kind === "surface" ? "Plane and heights" : "Heights"}>
          {e.kind === "obstacle" ? (
            <div className="grid2">
              <Field label="Base Z" unit="m">
                <NumberInput value={plane.mode === "flat" ? plane.z_m : 0} onChange={(z) => setPlane({ mode: "flat", z_m: z })} />
              </Field>
              <Field label="Height" unit="m">
                <NumberInput value={e.height_m} onChange={(h) => update({ height_m: h }, "planeDefinition")} />
              </Field>
            </div>
          ) : (
            <>
              <Field label="Plane definition">
                <Select
                  value={plane.mode}
                  onChange={(mode) => {
                    if (mode === "flat") setPlane({ mode: "flat", z_m: plane.mode === "flat" ? plane.z_m : 0 });
                    if (mode === "edge_tilt") setPlane({ mode: "edge_tilt", edgeIndex: 0, zRef_m: plane.mode === "flat" ? plane.z_m : 8, tilt_deg: 5, direction: "down" });
                    if (mode === "datum_tilt_azimuth") setPlane({ mode: "datum_tilt_azimuth", datum: centroid(e.polygon), z_m: 8, tilt_deg: 5, slopeAzimuth_deg: 180 });
                  }}
                  options={[
                    { value: "flat", label: "Flat at elevation" },
                    { value: "edge_tilt", label: "Reference edge + tilt" },
                    { value: "datum_tilt_azimuth", label: "Datum + tilt + slope azimuth" }
                  ]}
                />
              </Field>
              {plane.mode === "flat" && (
                <Field label="Elevation Z" unit="m">
                  <NumberInput value={plane.z_m} onChange={(z) => setPlane({ ...plane, z_m: z })} />
                </Field>
              )}
              {plane.mode === "edge_tilt" && (
                <div className="grid2">
                  <Field label="Reference edge">
                    <Select
                      value={String(plane.edgeIndex)}
                      onChange={(s) => setPlane({ ...plane, edgeIndex: Number(s) })}
                      options={e.polygon.map((_, i) => ({ value: String(i), label: `${label(i)}${label((i + 1) % e.polygon.length)}` }))}
                    />
                  </Field>
                  <Field label="Edge Z" unit="m">
                    <NumberInput value={plane.zRef_m} onChange={(z) => setPlane({ ...plane, zRef_m: z })} />
                  </Field>
                  <Field label="Tilt" unit="°">
                    <NumberInput value={plane.tilt_deg} step={0.5} min={0} max={80} onChange={(t) => setPlane({ ...plane, tilt_deg: t })} />
                  </Field>
                  <Field label="Slope">
                    <Select
                      value={plane.direction}
                      onChange={(direction) => setPlane({ ...plane, direction })}
                      options={[
                        { value: "down", label: "Falls from edge" },
                        { value: "up", label: "Rises from edge" }
                      ]}
                    />
                  </Field>
                </div>
              )}
              {plane.mode === "datum_tilt_azimuth" && (
                <div className="grid2">
                  <Field label="Datum Z" unit="m">
                    <NumberInput value={plane.z_m} onChange={(z) => setPlane({ ...plane, z_m: z })} />
                  </Field>
                  <Field label="Tilt" unit="°">
                    <NumberInput value={plane.tilt_deg} step={0.5} onChange={(t) => setPlane({ ...plane, tilt_deg: t })} />
                  </Field>
                  <Field label="Downslope azimuth" unit="° from N, cw">
                    <NumberInput value={plane.slopeAzimuth_deg} step={1} onChange={(a) => setPlane({ ...plane, slopeAzimuth_deg: a })} />
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
                  </tr>
                </thead>
                <tbody>
                  {e.polygon.map((p, i) => {
                    const z = planeZ(e.polygon, plane, p);
                    const isRef = plane.mode === "edge_tilt" && (i === plane.edgeIndex || i === (plane.edgeIndex + 1) % e.polygon.length);
                    return (
                      <tr key={i}>
                        <td>{label(i)}</td>
                        <td className="num">{f3(p[0])}</td>
                        <td className="num">{f3(p[1])}</td>
                        <td className="num">{z == null ? "—" : f3(z)}</td>
                        <td className="sub">{plane.mode === "flat" ? "plane" : isRef ? "reference" : "derived (preview)"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <p className="note">
                Heights shown are a browser preview of the plane rule. The engine derives canonical Z with provenance on commit <NotWired id="planeDefinition" compact />
              </p>
            </>
          )}
        </Section>
      )}


      <Section title="Danger zone" defaultOpen={false}>
        <Button tone="danger" small disabled={e.locked} onClick={() => window.dispatchEvent(new CustomEvent("rawibumi:delete-request", { detail: e.id }))}>
          Delete {e.kind}
        </Button>
      </Section>
    </div>
  );
}


function label(i: number) {
  return i < 26 ? String.fromCharCode(65 + i) : `V${i + 1}`;
}


function f3(v: number) {
  return (Math.abs(v) < 5e-4 ? 0 : v).toFixed(3);
}