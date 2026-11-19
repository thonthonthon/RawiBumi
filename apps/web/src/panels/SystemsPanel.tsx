import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { engine } from "../client";
import { useForm, useStore } from "../state/store";
import { engineCommand } from "../state/history";
import { InverterLifecycle, SuggestStringing, EngineDraftChecks } from "../electrical/InverterTools";
import { formatNotation, parseNotation } from "../electrical/notation";
import { pickable, useShowTestComponents } from "../ui/testComponents";
import type { CatalogModule, InverterSizing, ProjectView, SceneCommandInput, SystemsOverview } from "../types";
import { Button, Check, Field, Section, Select } from "../ui/kit";

export function suggestedBuildingCommands(view: SystemsOverview): SceneCommandInput[] {
  return view.suggested_buildings.filter(b => !b.matches_confirmed).map(b => ({ command_type: "group",
    target_entity_ids: b.surface_ids, parameters: { group_id: `building-${b.surface_ids.join("-")}`, name: b.name } }));
}

export function orientationGroupLabel(group: SystemsOverview["orientation_groups"][number],
  groups: SystemsOverview["orientation_groups"], modules: CatalogModule[]): string {
  if (!groups.some(other => other !== group && other.label === group.label)) return group.label;
  const models = group.module_definition_revision_ids.map(id => modules.find(m => m.revision_id === id)?.model ?? id);
  return `${group.label} · ${models.join(", ")}`;
}

export function SystemsPanel() {
  const { state, dispatch, run, toast } = useStore();
  const { t } = useTranslation();
  const view = state.view!;
  const pid = view.bundle.project.project_id;
  const [overview, setOverview] = useState<SystemsOverview | null>(null);
  const [threshold, setThreshold] = useState(String(view.bundle.project.distance_warning_m ?? 50));
  const [first, setFirst] = useState("");
  const [second, setSecond] = useState("");
  useEffect(() => {
    setThreshold(String(view.bundle.project.distance_warning_m ?? 50));
  }, [view.bundle.project.distance_warning_m]);
  useEffect(() => {
    let live = true;
    engine.systemsOverview(pid).then(next => {
      if (live) setOverview(next);
    }).catch(e => { if (live) toast("error", e instanceof Error ? e.message : String(e)); });
    return () => { live = false; };
  }, [pid, view.bundle.scene.revision_id, view.bundle.project.distance_warning_m, toast]);
  async function commands(items: SceneCommandInput[]) {
    await run(t("systems.saving"), async () => {
      for (const command of items) {
        const next = await engine.sceneCommand(pid, command);
        dispatch({ type: "setView", view: next });
      }
      setOverview(await engine.systemsOverview(pid));
    });
  }
  const roofName = (id: string) => view.bundle.scene.surfaces.find(s => s.surface_id === id)?.name ?? id;
  const buildingName = (id: string | null) => id === null ? t("systems.ungrouped") : overview?.buildings.find(b => b.building_id === id)?.name ?? id;
  const confirmed = overview?.buildings.filter(b => b.building_id !== null) ?? [];
  const busy = !!state.busy;
  const choices = [{ value: "", label: t("systems.choose") }, ...confirmed.map(b => ({ value: b.building_id!, label: b.name }))];
  return <div data-systems-panel>
    {overview && <SystemsInverters overview={overview} />}
    <Section primary title={t("systems.buildings")}>
      <p className="note">{t("systems.help")}</p>
      {!confirmed.length && <p>{t("systems.empty")}</p>}
      {overview?.buildings.map((b, i) => <div className="card-row" key={b.building_id ?? `ungrouped-${i}`}>
        {b.building_id === null ? <strong>{b.name}</strong> : <Field label={t("systems.rename", { name: b.name })}>
          <input key={b.name} className="input" defaultValue={b.name} maxLength={80} disabled={busy} onBlur={e => {
            if (e.currentTarget.value !== b.name) void commands([{ command_type: "group", target_entity_ids: b.surface_ids,
              parameters: { group_id: b.building_id!, name: e.currentTarget.value } }]);
          }} />
        </Field>}
        <p>{t("systems.modules", { count: b.module_count })} · {b.stc_kwp.toFixed(2)} kWp</p>
        {b.surface_ids.map(id => <div className="row" key={id}><span>{roofName(id)}</span>
          {b.building_id !== null && <Button small disabled={busy} onClick={() => void commands([{ command_type: "ungroup", target_entity_ids: [id], parameters: {} }])}>{t("systems.split", { roof: roofName(id) })}</Button>}
        </div>)}
      </div>)}
      <Button disabled={busy || !overview || !suggestedBuildingCommands(overview).length} onClick={() => overview && void commands(suggestedBuildingCommands(overview))}>{t("systems.suggest")}</Button>
      {confirmed.length > 1 && <>
        <Field label={t("systems.first")}><Select value={first} onChange={setFirst} options={choices} disabled={busy} /></Field>
        <Field label={t("systems.second")}><Select value={second} onChange={setSecond} options={choices} disabled={busy} /></Field>
        <Button disabled={busy || !first || !second || first === second || !confirmed.some(b => b.building_id === first) || !confirmed.some(b => b.building_id === second)} onClick={() => void commands([{ command_type: "group", target_entity_ids: confirmed.filter(b => b.building_id === first || b.building_id === second).flatMap(b => b.surface_ids), parameters: { group_id: first } }])}>{t("systems.merge")}</Button>
      </>}
    </Section>
    <Section title={t("sections.checks")}>
      <Field label={t("systems.threshold")} unit="m"><input className="input" type="number" min={0} max={10000} value={threshold} disabled={busy} onChange={e => setThreshold(e.currentTarget.value)} /></Field>
      <Button disabled={busy || !Number.isFinite(Number(threshold)) || !threshold.trim() || Number(threshold) < 0 || Number(threshold) > 10000} onClick={() => void run(t("systems.saving"), async () => {
        const next = await engine.updateProject(pid, { distance_warning_m: Number(threshold) });
        dispatch({ type: "setView", view: next }); setOverview(await engine.systemsOverview(pid));
      })}>{t("systems.saveThreshold")}</Button>
      {!overview?.distances.length ? <p>{t("systems.noDistances")}</p> : <table><thead><tr><th>{t("systems.from")}</th><th>{t("systems.to")}</th><th>{t("systems.distance")}</th></tr></thead><tbody>
        {overview.distances.map(d => <tr key={`${d.from_index}-${d.to_index}`}><td>{overview.buildings[d.from_index].name}</td><td>{overview.buildings[d.to_index].name}</td><td>{d.distance_m.toFixed(1)} m {d.over_threshold && <span className="note note--warn" data-distance-warning>{t("systems.tooFar")}</span>}</td></tr>)}
      </tbody></table>}

      <p className="note">{t("systems.orientationHelp", { tolerance: overview?.tolerance_deg ?? "…" })}</p>
      {!overview?.orientation_groups.length && <p>{t("systems.noOrientations")}</p>}
      {overview?.orientation_groups.map((g, i) => <div className="card-row" data-orientation-group key={i}><strong>{orientationGroupLabel(g, overview.orientation_groups, view.catalog.modules)}</strong>
        <p>{g.surface_ids.map(roofName).join(", ")}</p><p>{g.building_ids.map(buildingName).join(", ")}</p>
        <p>{t("systems.modules", { count: g.module_count })} · {g.stc_kwp.toFixed(2)} kWp</p>
      </div>)}
    </Section>
  </div>;
}


export function servesFieldIds(buildings: SystemsOverview["buildings"], selected: number[]): string[] {
  return [...new Set(selected.flatMap(i => buildings[i].pv_field_ids))];
}
export function inverterSourceOptions(overview: SystemsOverview, area: string[]) {
  return overview.orientation_groups.flatMap(g => {
    const ids = g.pv_field_ids.filter(id => area.includes(id));
    return ids.length ? [{ value: JSON.stringify(ids), label: g.label, fields: ids }] : [];
  });
}
export function mixesOrientations(source: string[] | null, area: string[], overview: SystemsOverview, mismatch = false): boolean {
  return mismatch || overview.orientation_groups.filter(g => g.pv_field_ids.some(id => (source ?? area).includes(id))).length > 1;
}
export function invertersForTarget(areaKwp: number, acKw: number, target: number): number | null {
  return Number.isFinite(target) && target > 0 && acKw > 0 ? Math.ceil(areaKwp / (acKw * target)) : null;
}
export function tableRowLayout(length: number, count: number): number[] {
  return count > 0 ? Array(count).fill(length) : [0];
}
function SystemsInverters({ overview }: { overview: SystemsOverview }) {
  const { state } = useStore(), { t } = useTranslation();
  const view = state.view!, pid = view.bundle.project.project_id;
  const [showTest] = useShowTestComponents();
  const choices = pickable(view.catalog.inverters, showTest);
  const [model, setModel] = useState("");
  const [count, setCount] = useState("1");
  const revision = choices.some(d => d.revision_id === model) ? model : choices[0]?.revision_id ?? "";
  return <Section primary title={t("systems.inverters")}>
    <Field label={t("systems.inverterModel")}><Select value={revision} onChange={setModel} options={choices.map(d => ({ value: d.revision_id, label: d.model }))} disabled={!!state.busy} /></Field>
    <Field label={t("systems.inverterCount")}><input className="input" type="number" min={1} step={1} value={count} onChange={e => setCount(e.currentTarget.value)} disabled={!!state.busy} /></Field>
    <Button disabled={!!state.busy || !revision || !Number.isInteger(Number(count)) || Number(count) < 1} onClick={async () => {
      for (let i = 0; i < Number(count); i++) {
        const next = await engineCommand(t("systems.saving"), () => engine.addInverter(pid, { inverter_definition_revision_id: revision, name: `${choices.find(d => d.revision_id === revision)?.model ?? revision} ${i + 1}` }));
        if (!next) break;
      }
    }}>{t("systems.addInverters")}</Button>
    {!view.bundle.electrical_design.inverter_instances.length && <p>{t("systems.noInverters")}</p>}
    {view.bundle.electrical_design.inverter_instances.map(inv => <SystemsInverter key={inv.inverter_instance_id} inv={inv} overview={overview} />)}
  </Section>;
}
function SystemsInverter({ inv, overview }: { inv: ProjectView["bundle"]["electrical_design"]["inverter_instances"][number]; overview: SystemsOverview }) {
  const { state, toast } = useStore(), { t } = useTranslation();
  const view = state.view!, pid = view.bundle.project.project_id;
  const [sizing, setSizing] = useState<InverterSizing | null>(null);
  const fields = view.bundle.scene.pv_fields.map(f => f.pv_field_id);
  const storedArea = inv.paired_pv_field_ids?.length ? inv.paired_pv_field_ids : fields;
  const storedAreaKey = JSON.stringify([...storedArea].sort());
  const [area, setArea] = useState<string[]>(storedArea);
  useEffect(() => { setArea(storedArea); }, [storedAreaKey]);
  const actual = view.topology_view.inverters.find(i => i.inverter_instance_id === inv.inverter_instance_id);
  const current = actual?.mppts.map(m => m.strings.length ? m.strings.map(s => s.module_count) : [0]) ?? [];
  const [text, setText] = useState(formatNotation({ mppts: current }));
  const [sources, setSources] = useState<(string[] | null)[]>(inv.mppt_instance_ids.map(() => null));
  const [replace, setReplace] = useState<string[]>([]);
  const [mixed, setMixed] = useState<number[]>([]);
  const [target, setTarget] = useForm<{ value: string }>("systems.dcAcTarget", { value: "1.25" });
  const busy = !!state.busy;
  const def = view.catalog.inverters.find(d => d.revision_id === inv.inverter_definition_revision_id);
  useEffect(() => {
    let live = true;
    engine.inverterSizing(pid, inv.inverter_instance_id).then(next => { if (live) setSizing(next); })
      .catch(e => { if (live) { setSizing(null); toast("error", e instanceof Error ? e.message : String(e)); } });
    return () => { live = false; };
  }, [pid, inv.inverter_instance_id, view.bundle.electrical_design.electrical_revision_id, view.bundle.scene.revision_id, view.bundle.project.distance_warning_m, toast]);
  useEffect(() => {
    setText(formatNotation({ mppts: current })); setReplace([]); setMixed([]);
    setSources(previous => inv.mppt_instance_ids.map((_, i) => previous[i] ?? null));
  }, [JSON.stringify(current), inv.inverter_definition_revision_id]);
  const parsed = parseNotation(text);
  const options = inverterSourceOptions(overview, area);
  const rows = inv.mppt_instance_ids.map((_, i) => parsed.layout?.mppts[i] ?? [0]);
  const sourceRows = inv.mppt_instance_ids.map((_, i) => sources[i] ?? null);
  const cap = (i: number) => {
    const spec = sizing?.mppts[i];
    return Math.min(spec?.inputs ?? Infinity, spec?.max_strings_by_isc ?? Infinity);
  };
  const valid = parsed.layout && parsed.layout.mppts.length === inv.mppt_instance_ids.length && rows.every((r, i) => r.filter(n => n > 0).length <= cap(i));
  const updateRow = (i: number, length: number, count: number) => {
    if (!Number.isInteger(length) || length < 0 || !Number.isInteger(count) || count < 0) return;
    const next = rows.map((r, j) => j === i ? tableRowLayout(length, Math.min(count, cap(i))) : r);
    setText(formatNotation({ mppts: next })); setReplace([]);
  };
  const n = sizing ? invertersForTarget(sizing.area_kwp, sizing.ac_kw, Number(target.value)) : null;
  const areaSaved = sizing && JSON.stringify([...area].sort()) === JSON.stringify([...sizing.pv_field_ids].sort());
  return <div className="card-row" data-systems-inverter={inv.inverter_instance_id}>
    <h3>{inv.name} · {def?.model ?? inv.inverter_definition_revision_id}</h3>
    <InverterLifecycle inv={inv} def={def} />
    <h4>{t("systems.serves")}</h4>
    {overview.buildings.map((b, i) => <Check key={i} label={b.name} disabled={busy || !b.pv_field_ids.length} checked={!!b.pv_field_ids.length && b.pv_field_ids.every(id => area.includes(id))} onChange={checked => {
      setArea(checked ? [...new Set([...area, ...servesFieldIds(overview.buildings, [i])])] : area.filter(id => !b.pv_field_ids.includes(id)));
    }} />)}
    <Button disabled={busy || JSON.stringify([...area].sort()) === storedAreaKey} onClick={() => void engineCommand(t("systems.saving"), async () => {
      const next = await engine.topologyCommand(pid, { command_type: "set_inverter_pairing", parameters: { inverter_instance_id: inv.inverter_instance_id, pv_field_ids: area } });
      const savedPairing = next.bundle.electrical_design.inverter_instances.find(i => i.inverter_instance_id === inv.inverter_instance_id)?.paired_pv_field_ids;
      setArea(savedPairing?.length ? savedPairing : next.bundle.scene.pv_fields.map(f => f.pv_field_id));
      setSources(inv.mppt_instance_ids.map(() => null)); return next;
    })}>{t("systems.saveArea")}</Button>
    {sizing && <>
      <p>{sizing.area_kwp.toFixed(2)} kWp · {sizing.ac_kw.toFixed(2)} kW AC · DC/AC {sizing.dc_ac_ratio?.toFixed(2) ?? "—"}</p>
      {!!sizing.distance_warnings.length && <p className="note note--warn" data-area-distance-warning>{t("systems.tooFar")} {sizing.distance_warnings.map(d => `${d.from_name} / ${d.to_name}: ${d.distance_m.toFixed(1)} m`).join(", ")}</p>}
      <p>{t("systems.stringRange", { min: sizing.string_length_min ?? "—", max: sizing.string_length_max ?? "—" })}</p>
      {sizing.reasons.map(r => <p className="note" key={r.code}>{r.message}</p>)}
      <Field label={t("systems.dcAcTarget")}><input className="input" type="number" min={0.01} step={0.05} value={target.value} onChange={e => setTarget({ value: e.currentTarget.value })} /></Field>
      {n !== null && <p data-inverter-target>{t("systems.targetCount", { count: n, target: target.value })}</p>}
    </>}
    <table><thead><tr><th>MPPT</th><th>{t("systems.source")}</th><th>{t("systems.stringLength")}</th><th>{t("systems.strings")}</th></tr></thead><tbody>
      {rows.map((row, i) => <tr key={inv.mppt_instance_ids[i]}><td>{i + 1}</td><td>
        <Select label={t("systems.mpptSource", { index: i + 1 })} value={sources[i] === null || !sources[i] ? "" : JSON.stringify(sources[i])} onChange={value => setSources(previous => previous.map((s, k) => k === i ? value ? JSON.parse(value) as string[] : null : s))}
          options={[{ value: "", label: t("systems.anySource") }, ...options]} disabled={busy} />
        {mixesOrientations(sourceRows[i], area, overview, mixed.includes(i)) && <p className="note note--warn" data-mixed-orientation>{t("systems.mixedOrientation")}</p>}
      </td><td><input className="input" aria-label={t("systems.mpptLength", { index: i + 1 })} type="number" min={0} step={1} value={row.find(n => n > 0) ?? 0} disabled={busy} onChange={e => updateRow(i, Number(e.currentTarget.value), row.filter(n => n > 0).length || 1)} /></td>
      <td><input className="input" aria-label={t("systems.mpptStrings", { index: i + 1 })} type="number" min={0} step={1} max={Number.isFinite(cap(i)) ? cap(i) : undefined} value={row.filter(n => n > 0).length} disabled={busy} onChange={e => updateRow(i, row.find(n => n > 0) ?? sizing?.string_length_min ?? 1, Number(e.currentTarget.value))} />
        <p className="sub">{t("systems.inputs", { count: sizing?.mppts[i]?.inputs ?? "—", source: sizing?.mppts[i]?.inputs_source ?? "—" })}</p>
        {sizing?.mppts[i]?.max_strings_by_isc !== null && sizing?.mppts[i]?.max_strings_by_isc !== undefined && sizing.mppts[i].max_strings_by_isc! < (sizing.mppts[i].inputs ?? Infinity) && <p className="sub">{t("systems.iscCap", { count: sizing.mppts[i].max_strings_by_isc })}</p>}
      </td></tr>)}
    </tbody></table>
    <Field label={t("systems.notation")}><input className="input" value={text} disabled={busy} onChange={e => { setText(e.currentTarget.value); setReplace([]); }} /></Field>
    {parsed.issues.map((issue, i) => <p className="note" key={i}>{issue.message}</p>)}
    <SuggestStringing inv={inv} pairedFieldIds={area} onLayout={(layout, ids) => { setText(formatNotation(layout)); setReplace(ids); setSources(inv.mppt_instance_ids.map(() => null)); }} />
    <EngineDraftChecks inverterId={inv.inverter_instance_id} layout={valid ? parsed.layout : null} pairedFieldIds={area} text={text} replace={replace} sources={sourceRows} onOrientationMismatch={setMixed} />
    <Button disabled={busy || !valid || !areaSaved} onClick={() => parsed.layout && void engineCommand(t("systems.saving"), () => engine.applyLayoutReplacing(pid, inv.inverter_instance_id, parsed.layout!.mppts, area, replace, sourceRows))}>{t("systems.applyMppt")}</Button>
  </div>;
}
