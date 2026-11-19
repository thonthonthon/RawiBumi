import { engine } from "../client";
import { checkLayout, formatNotation, MpptLayout, parseNotation, stringCount, totalModules } from "../electrical/notation";
import { normalAngleDeg } from "../geometry";
import { useForm, useStore } from "../state/store";
import { modulesPerField } from "../state/derived";
import { Button, Check, Field, fmt, NotWired, NumberInput, PendingBlock, Section, Select, StatusDot } from "../ui/kit";

export function ElectricalPanel() {
  const { state, dispatch, run, toast } = useStore();
  const v = state.view!;
  const pid = v.bundle.project.project_id;
  const [add, setAdd] = useForm("elec.add", { def: v.catalog.inverters[0]?.revision_id ?? "", name: `INV-${String(v.bundle.electrical_design.inverter_instances.length + 1).padStart(2, "0")}` });
  const [uni, setUni] = useForm("elec.uniform", { len: 16, field: "", remainder: false });
  const [tol, setTol] = useForm("elec.tol", 1.0);
  const perField = modulesPerField(state);

  return (
    <>
      <Section title="Inverters">
        <div className="grid2">
          <Field label="Model">
            <Select
              value={add.def}
              onChange={(def) => setAdd({ ...add, def })}
              options={v.catalog.inverters.map((i) => ({ value: i.revision_id, label: `${i.model} · ${i.mppt_count} MPPT` }))}
            />
          </Field>
          <Field label="Name">
            <input className="input" value={add.name} onChange={(e) => setAdd({ ...add, name: e.target.value })} />
          </Field>
        </div>
        <Button
          small
          onClick={async () => {
            const r = await run("Adding inverter", () => engine.addInverter(pid, { inverter_definition_revision_id: add.def, name: add.name }));
            if (r) dispatch({ type: "setView", view: r });
          }}
        >
          Add inverter
        </Button>
      </Section>

      <Section title="Orientation rule" aside={<NotWired id="orientationPolicy" compact />}>
        <div className="grid2">
          <Field label="Same-orientation tolerance" unit="°" hint="Max pairwise angle between module normals">
            <NumberInput value={tol} step={0.1} min={0} onChange={setTol} />
          </Field>
          <Field label="Default">
            <input className="input" value="1 MPPT = 1 orientation" readOnly />
          </Field>
        </div>
      </Section>

      {v.bundle.electrical_design.inverter_instances.map((inv) => {
        const d = state.electrical[inv.inverter_instance_id];
        if (!d) return null;
        const def = v.catalog.inverters.find((i) => i.revision_id === inv.inverter_definition_revision_id);
        const parsed = parseNotation(d.notation);
        const available = d.pairedFieldIds.length ? d.pairedFieldIds.reduce((t, f) => t + (perField[f] ?? 0), 0) : null;
        const res = parsed.layout
          ? checkLayout({ layout: parsed.layout, mpptCount: def?.mppt_count ?? null, inputsPerMppt: d.inputsPerMppt, modulesAvailable: available, unequalParallelPolicy: "warning" })
          : null;
        const kwp = d.pairedFieldIds.reduce((t, fid) => {
          const fl = v.bundle.scene.pv_fields.find((x) => x.pv_field_id === fid);
          const m = v.catalog.modules.find((x) => x.revision_id === fl?.module_definition_revision_id);
          return t + ((perField[fid] ?? 0) * (m?.pmp_w ?? 0)) / 1000;
        }, 0);
        const setD = (patch: Partial<typeof d>) => dispatch({ type: "setElectrical", inverterId: inv.inverter_instance_id, patch });
        const setLayout = (l: MpptLayout) => setD({ notation: formatNotation(l) });
        const width = Math.max(d.inputsPerMppt ?? 1, ...(parsed.layout?.mppts.map((m) => m.length) ?? [1]));
        const topo = v.topology_view.inverters.find((t) => t.inverter_instance_id === inv.inverter_instance_id);

        // Orientation per MPPT from the fields its current strings draw from.
        const mpptOrientation = (idx: number) => {
          const mppt = topo?.mppts[idx];
          if (!mppt) return null;
          const fields = new Set<string>();
          for (const s of mppt.strings) {
            const str = v.bundle.electrical_design.strings.find((x) => x.string_id === s.string_id);
            for (const mid of str?.module_instance_ids ?? []) {
              const mi = v.bundle.scene.module_instances.find((x) => x.module_instance_id === mid);
              if (mi) fields.add(mi.pv_field_id);
            }
          }
          const fl = [...fields].map((id) => v.bundle.scene.pv_fields.find((x) => x.pv_field_id === id)).filter(Boolean) as typeof v.bundle.scene.pv_fields;
          if (!fl.length) return null;
          let spread = 0;
          for (const a of fl) for (const b of fl) spread = Math.max(spread, normalAngleDeg(a.tilt_deg, a.azimuth_deg, b.tilt_deg, b.azimuth_deg));
          return { spread, label: fl.length === 1 ? `${fl[0].tilt_deg}° / ${fl[0].azimuth_deg}°` : `${fl.length} orientations` };
        };

        return (
          <Section key={inv.inverter_instance_id} title={`${inv.name} · ${def?.model ?? inv.inverter_definition_revision_id}`}>
            <div className="statline">
              <span>{fmt((def?.nominal_ac_power_w ?? 0) / 1000, 0, "kW AC")}</span>
              <span>{def?.mppt_count ?? "?"} MPPT</span>
              <span>{fmt(kwp, 2, "kWp paired")}</span>
              <span>DC/AC {def && kwp ? (kwp / (def.nominal_ac_power_w / 1000)).toFixed(2) : "—"}</span>
            </div>

            <Field label="Paired PV fields">
              <div className="chips">
                {v.bundle.scene.pv_fields.map((fl) => {
                  const on = d.pairedFieldIds.includes(fl.pv_field_id);
                  return (
                    <button
                      key={fl.pv_field_id}
                      type="button"
                      className={on ? "chip chip--on" : "chip"}
                      onClick={() => setD({ pairedFieldIds: on ? d.pairedFieldIds.filter((x) => x !== fl.pv_field_id) : [...d.pairedFieldIds, fl.pv_field_id] })}
                    >
                      {fl.name} <span className="count">{perField[fl.pv_field_id] ?? 0}</span>
                    </button>
                  );
                })}
                <NotWired id="tablePairing" compact />
              </div>
            </Field>

            <div className="grid2">
              <Field label="Inputs per MPPT" hint="Not in the inverter summary; enter from the datasheet">
                <NumberInput value={d.inputsPerMppt ?? 0} step={1} min={1} onChange={(n) => setD({ inputsPerMppt: n > 0 ? n : null })} />
              </Field>
              <Field label="Source for inputs per MPPT">
                <input className="input" value={d.inputsSource} placeholder="e.g. datasheet rev. 2024-03, p. 2" onChange={(e) => setD({ inputsSource: e.target.value })} />
              </Field>
            </div>

            <Field label="MPPT layout" hint="MPPTs separated by ;  inputs by ,  0 = empty input. Shorthand 3x(16,0) repeats.">
              <input className={parsed.layout ? "input input--notation" : "input input--notation input--bad"} value={d.notation} onChange={(e) => setD({ notation: e.target.value })} spellCheck={false} />
            </Field>
            {parsed.layout && (
              <div className="statline statline--quiet">
                <span>{parsed.layout.mppts.length} MPPT groups</span>
                <span>{stringCount(parsed.layout)} strings</span>
                <span>{totalModules(parsed.layout)} modules</span>
              </div>
            )}
            {parsed.issues
              .filter((i) => i.severity === "blocking")
              .map((i) => (
                <div className="issue issue--blocking" key={i.message}>
                  {i.message}
                </div>
              ))}

            {parsed.layout && (
              <table className="tbl mppt-grid">
                <thead>
                  <tr>
                    <th>MPPT</th>
                    {Array.from({ length: width }, (_, i) => (
                      <th key={i} className="num">
                        In {i + 1}
                      </th>
                    ))}
                    <th>Orientation</th>
                    <th>Override</th>
                  </tr>
                </thead>
                <tbody>
                  {parsed.layout.mppts.map((row, r) => {
                    const o = mpptOrientation(r);
                    const ov = d.overrides[r] ?? { on: false, reason: "" };
                    const mixed = o ? o.spread > tol : false;
                    return (
                      <tr key={r} className={res?.issues.some((i) => i.mppt === r && i.severity !== "info") ? "row--warn" : ""}>
                        <td>{r + 1}</td>
                        {Array.from({ length: width }, (_, c) => (
                          <td key={c} className="num">
                            <input
                              className="cell"
                              type="number"
                              min={0}
                              value={row[c] ?? 0}
                              onChange={(e) => {
                                const l = parsed.layout!.mppts.map((m) => [...m, ...Array(Math.max(0, width - m.length)).fill(0)]);
                                l[r][c] = Math.max(0, Math.trunc(Number(e.target.value) || 0));
                                setLayout({ mppts: l });
                              }}
                            />
                          </td>
                        ))}
                        <td>
                          {o ? (
                            <span className={mixed ? "orient orient--mixed" : "orient"}>
                              <StatusDot state={mixed ? (ov.on ? "warn" : "fail") : "pass"} /> {o.label}
                              {o.spread >= 0.05 && ` · Δ${o.spread.toFixed(1)}°`}
                            </span>
                          ) : (
                            <span className="sub">no strings yet</span>
                          )}
                        </td>
                        <td>
                          <Check checked={ov.on} onChange={(on) => setD({ overrides: { ...d.overrides, [r]: { ...ov, on } } })} label="" />
                          {ov.on && (
                            <input
                              className="input input--inline"
                              placeholder="Reason (required)"
                              value={ov.reason}
                              onChange={(e) => setD({ overrides: { ...d.overrides, [r]: { ...ov, reason: e.target.value } } })}
                            />
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}

            {res && (
              <ul className="checklist">
                {res.checks.map((c) => (
                  <li key={c.id}>
                    <StatusDot state={c.state} />
                    <span className="checklist__label">{c.label}</span>
                    <span className="checklist__detail">{c.detail}</span>
                  </li>
                ))}
              </ul>
            )}

            <div className="row">
              <Button small tone="primary" onClick={() => toast("pending", "Applying an MPPT layout needs POST /electrical/mppt-layout (not wired). Use uniform strings below meanwhile.")}>
                Apply layout
              </Button>
              <NotWired id="notationApply" compact />
              <Button
                small
                onClick={async () => {
                  const r = await run("Assigning strings", () => engine.assignStrings(pid, { inverter_instance_id: inv.inverter_instance_id, string_ids: null }));
                  if (r) dispatch({ type: "setView", view: r });
                }}
                disabled={v.topology_view.unassigned_strings.length === 0}
              >
                Assign unassigned ({v.topology_view.unassigned_strings.length})
              </Button>
            </div>
          </Section>
        );
      })}

      <Section title="Uniform strings (wired fallback)" defaultOpen={false}>
        <div className="grid2">
          <Field label="Modules per string">
            <NumberInput value={uni.len} step={1} min={1} onChange={(len) => setUni({ ...uni, len })} />
          </Field>
          <Field label="PV field">
            <Select value={uni.field} onChange={(field) => setUni({ ...uni, field })} options={[{ value: "", label: "All unstrung" }, ...v.bundle.scene.pv_fields.map((f) => ({ value: f.pv_field_id, label: f.name }))]} />
          </Field>
        </div>
        <Check checked={uni.remainder} onChange={(remainder) => setUni({ ...uni, remainder })} label="Allow a shorter remainder string" />
        <Button
          small
          onClick={async () => {
            const r = await run("Creating strings", () => engine.createStrings(pid, { string_length: uni.len, pv_field_id: uni.field || null, allow_shorter_remainder: uni.remainder }));
            if (r) dispatch({ type: "setView", view: r });
          }}
        >
          Create strings
        </Button>
      </Section>

      <Section title="String routing" defaultOpen={false}>
        <PendingBlock id="notationApply" note="Auto-trace by pattern or click a path across modules on the canvas. Warns when a string spans distant tables.">
          <div className="row wrap">
            {["Row-wise", "Serpentine", "Per table", "Manual click-path"].map((l) => (
              <button key={l} type="button" className="btn btn--sm" disabled>
                {l}
              </button>
            ))}
          </div>
        </PendingBlock>
      </Section>
    </>
  );
}
