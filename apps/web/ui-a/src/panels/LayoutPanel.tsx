import { engine } from "../client";
import { useForm, useStore } from "../state/store";
import { modulesPerField } from "../state/derived";
import { Button, Field, fmt, NumberInput, PendingBlock, Section, Segmented, Select } from "../ui/kit";

export function LayoutPanel() {
  const { state, dispatch, run, toast } = useStore();
  const v = state.view!;
  const surfaces = v.bundle.scene.surfaces;
  const readyModule = v.catalog.modules.find((m) => m.simulation_ready) ?? v.catalog.modules[0];
  const [f, setF] = useForm("layout.form", {
    name: "Roof array",
    surface: surfaces[0]?.surface_id ?? "",
    module: readyModule?.revision_id ?? "",
    orientation: "portrait",
    azimuth: 0,
    tilt: 10,
    pitch: 2.6,
    gapX: 0.02,
    gapY: 0.02,
    mount: 0.2,
    edge: 0.3,
    obst: 0.3
  });
  const set = (patch: Partial<typeof f>) => setF({ ...f, ...patch });
  const perField = modulesPerField(state);
  const mod = v.catalog.modules.find((m) => m.revision_id === f.module);
  const draftSurfaces = state.entities.filter((e) => e.kind === "surface" && e.source === "draft");

  return (
    <>
      <Section title="PV fields">
        {v.bundle.scene.pv_fields.length === 0 && <div className="empty">No PV field yet. Fill a surface below.</div>}
        {v.bundle.scene.pv_fields.map((fl) => {
          const m = v.catalog.modules.find((x) => x.revision_id === fl.module_definition_revision_id);
          const n = perField[fl.pv_field_id] ?? 0;
          return (
            <div className="card-row" key={fl.pv_field_id}>
              <div>
                <strong>{fl.name}</strong>
                <div className="sub">
                  {n} modules · {fmt((n * (m?.pmp_w ?? 0)) / 1000, 2, "kWp")} · tilt {fl.tilt_deg}° · az {fl.azimuth_deg}°
                </div>
              </div>
              <span className="tag">{fl.orientation}</span>
            </div>
          );
        })}
      </Section>

      <Section title="Fill a surface">
        <Field label="Field name">
          <input className="input" value={f.name} onChange={(e) => set({ name: e.target.value })} />
        </Field>
        <Field label="Support surface" hint={draftSurfaces.length ? `${draftSurfaces.length} draft surface(s) can be filled once the polygon endpoint is wired.` : undefined}>
          <Select
            value={f.surface}
            onChange={(surface) => set({ surface })}
            options={[
              ...surfaces.map((s) => ({ value: s.surface_id, label: `${s.name} · ${s.surface_type}` })),
              ...draftSurfaces.map((s) => ({ value: s.id, label: `${s.name} (draft)`, disabled: true }))
            ]}
          />
        </Field>
        <Field label="Module">
          <Select value={f.module} onChange={(module) => set({ module })} options={v.catalog.modules.map((m) => ({ value: m.revision_id, label: `${m.manufacturer} ${m.model} · ${m.pmp_w} W` }))} />
        </Field>
        {mod && (
          <div className="sub">
            Footprint {mod.width_m.toFixed(3)} × {mod.height_m.toFixed(3)} m from the component revision (not stretchable)
          </div>
        )}
        <Field label="Orientation">
          <Segmented value={f.orientation} onChange={(orientation) => set({ orientation })} options={[{ value: "portrait", label: "Portrait" }, { value: "landscape", label: "Landscape" }]} />
        </Field>
        <div className="grid2">
          <Field label="Azimuth" unit="°" hint="Convention: to be confirmed with engine">
            <NumberInput value={f.azimuth} step={1} onChange={(azimuth) => set({ azimuth })} />
          </Field>
          <Field label="Tilt" unit="°">
            <NumberInput value={f.tilt} step={1} min={0} max={90} onChange={(tilt) => set({ tilt })} />
          </Field>
          <Field label="Row pitch" unit="m">
            <NumberInput value={f.pitch} step={0.05} onChange={(pitch) => set({ pitch })} />
          </Field>
          <Field label="Mounting height" unit="m">
            <NumberInput value={f.mount} step={0.05} onChange={(mount) => set({ mount })} />
          </Field>
          <Field label="Gap X" unit="m">
            <NumberInput value={f.gapX} step={0.01} onChange={(gapX) => set({ gapX })} />
          </Field>
          <Field label="Gap Y" unit="m">
            <NumberInput value={f.gapY} step={0.01} onChange={(gapY) => set({ gapY })} />
          </Field>
          <Field label="Edge setback" unit="m">
            <NumberInput value={f.edge} step={0.05} onChange={(edge) => set({ edge })} />
          </Field>
          <Field label="Obstacle setback" unit="m">
            <NumberInput value={f.obst} step={0.05} onChange={(obst) => set({ obst })} />
          </Field>
        </div>
        <Button
          tone="primary"
          disabled={!f.surface || !f.module}
          onClick={async () => {
            const res = await run("Filling area", () =>
              engine.createPvField(v.bundle.project.project_id, {
                name: f.name,
                support_surface_id: f.surface,
                module_definition_revision_id: f.module,
                orientation: f.orientation,
                azimuth_deg: f.azimuth,
                tilt_deg: f.tilt,
                module_gap_x_m: f.gapX,
                module_gap_y_m: f.gapY,
                row_pitch_m: f.pitch,
                mounting_height_m: f.mount,
                perimeter_setback_m: f.edge,
                obstacle_setback_m: f.obst
              })
            );
            if (res) {
              dispatch({ type: "setView", view: res });
              toast("ok", "PV field filled by the engine.");
            }
          }}
        >
          Fill area
        </Button>
      </Section>

      <Section title="Tables and modules">
        <PendingBlock id="moduleEdit" note="Select modules on the canvas (Shift adds to the selection). These commands apply once the endpoint exists; the engine already supports manual module edits (4.7H-B).">
          <div className="row wrap">
            {["Delete modules", "Add module", "Move", "Rotate", "Split table", "Merge tables", "Resize table"].map((l) => (
              <button key={l} className="btn btn--sm" type="button" disabled>
                {l}
              </button>
            ))}
          </div>
          <div className="sub">{state.selection.filter((id) => state.modules.some((m) => m.id === id)).length} modules selected</div>
        </PendingBlock>
        <PendingBlock id="moduleEdit" note="Suggestions are shown, never auto-applied.">
          <div className="grid2">
            <Field label="Suggest pitch from GCR">
              <NumberInput value={0.4} step={0.01} onChange={() => undefined} disabled />
            </Field>
            <Field label="or design sun elevation" unit="°">
              <NumberInput value={25} step={1} onChange={() => undefined} disabled />
            </Field>
          </div>
        </PendingBlock>
      </Section>
    </>
  );
}
