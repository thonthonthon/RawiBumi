import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { engine } from "../client";
import { useStore } from "../state/store";
import type { LossOverridePatch, LossPatch, ResolvedLossSettings, SimulationRunRecord, ProjectView, AcWiringSegment, CircuitOverridePatch, CircuitLossResolution } from "../types";
import { formatNumber, formatPercent } from "../formatNumbers";
import { Button, Field } from "../ui/kit";

/** UXF1 (U2-5): standard conductor sizes, IEC 60228 (mm²). A saved non-standard value stays selectable as custom. */
export const CABLE_SIZES_MM2 = [1.5, 2.5, 4, 6, 10, 16, 25, 35, 50, 70, 95, 120, 150, 185, 240, 300, 400, 500, 630] as const;
export const LOSS_FIELDS = ["lid_fraction", "module_mismatch_fraction", "string_mismatch_fraction", "dc_wiring_stc_fraction", "ac_wiring_nominal_fraction", "annual_degradation_fraction", "operating_year", "unavailability_fraction", "transformer.reference_power_w", "transformer.iron_fraction", "transformer.copper_fraction"] as const;
export type LossDraft = Record<string, string>;
export function lossDraft(settings: ResolvedLossSettings): LossDraft {
  const values = settings.values;
  const result: LossDraft = { "transformer.enabled": String(values.transformer.enabled) };
  for (const key of LOSS_FIELDS) {
    const value = key.startsWith("transformer.") ? values.transformer[key.split(".")[1] as "reference_power_w" | "iron_fraction" | "copper_fraction"] : values[key as keyof typeof values];
    result[key] = value == null ? "" : key === "operating_year" || key.endsWith("_w") ? formatNumber(Number(value)) : formatPercent(Number(value));
  }
  values.soiling.monthly_fractions.forEach((v, i) => { result[`month${i + 1}`] = formatPercent(v); });
  return result;
}
export function lossFormErrors(draft: LossDraft): string[] {
  const errors: string[] = [];
  for (const key of [...LOSS_FIELDS, ...Array.from({ length: 12 }, (_, i) => `month${i + 1}`)]) {
    const value = draft[key];
    if (!value?.trim() && (["lid_fraction", "module_mismatch_fraction", "string_mismatch_fraction", "transformer.reference_power_w"].includes(key) || key === "transformer.copper_fraction" && draft["transformer.enabled"] === "false")) continue;
    const n = value?.trim() ? Number(value) : NaN;
    const inclusive = key.startsWith("month") || key === "unavailability_fraction";
    if (!Number.isFinite(n) || (key === "operating_year" ? !Number.isInteger(n) || n < 1 || n > 100 : key.endsWith("_w") ? n <= 0 : n < 0 || (inclusive ? n > 100 : n >= 100))) errors.push(key);
  }
  if (Number(draft.annual_degradation_fraction) / 100 * (Number(draft.operating_year) - 0.5) >= 1) errors.push("annual_degradation_fraction");
  return [...new Set(errors)];
}
export function lossFormPatch(initial: LossDraft, draft: LossDraft): LossPatch {
  const overrides: Record<string, unknown> = {};
  for (const key of LOSS_FIELDS) {
    if (draft[key] === initial[key]) continue;
    const value = draft[key].trim() ? Number(draft[key]) / (key === "operating_year" || key.endsWith("_w") ? 1 : 100) : null;
    if (key.startsWith("transformer.")) overrides.transformer ??= {};
    if (key.startsWith("transformer.")) (overrides.transformer as Record<string, unknown>)[key.split(".")[1]] = value;
    else overrides[key] = value;
  }
  if (draft["transformer.enabled"] !== initial["transformer.enabled"]) {
    overrides.transformer ??= {};
    (overrides.transformer as Record<string, unknown>).enabled = draft["transformer.enabled"] === "true";
  }
  if (Array.from({ length: 12 }, (_, i) => `month${i + 1}`).some((k) => draft[k] !== initial[k])) overrides.soiling = { monthly_fractions: Array.from({ length: 12 }, (_, i) => Number(draft[`month${i + 1}`]) / 100) };
  return { overrides: overrides as LossOverridePatch };
}

export function moduleLid(settings: ResolvedLossSettings, module: { technology?: string; quality?: { lid_loss_fraction?: number | null } }) {
  if (settings.overrides.lid_fraction != null) return { fraction: settings.overrides.lid_fraction, source: "user" };
  if (settings.defaults_id === "recommended_defaults.v1") return { fraction: 0, source: "recommended_defaults" };
  const value = module.quality?.lid_loss_fraction;
  if (typeof value === "number" && Number.isFinite(value) && value >= 0 && value < 1) return { fraction: value, source: "module_file" };
  const technology = (module.technology ?? "").trim().toLowerCase();
  const fraction = ["topcon", "hjt", "heterojunction", "ibc"].some((name) => technology.includes(name)) ? .005
    : ["cdte", "cadmium_telluride", "cigs", "cis", "a_si", "amorphous_silicon", "thin_film", "thinfilm"].includes(technology) ? 0 : .015;
  return { fraction, source: "generic_default" };
}

export function LossesPanel({ defaults }: { defaults?: ResolvedLossSettings }) {
  const { state, dispatch, run } = useStore();
  const { t } = useTranslation();
  const view = state.view!;
  const settings = view.resolved_loss_settings ?? defaults;
  const [draft, setDraft] = useState<LossDraft>(() => settings ? lossDraft(settings) : {});
  useEffect(() => { setDraft(settings ? lossDraft(settings) : {}); }, [settings, view.bundle.project.project_id]);
  if (!settings) return <p role="status">{t("s7d.defaultsUnavailable")}</p>;
  const initial = lossDraft(settings), errors = lossFormErrors(draft);
  const changed = JSON.stringify(initial) !== JSON.stringify(draft);
  const modules = Object.entries(view.bundle.pinned_components?.modules ?? {}).filter(([, module]) => module != null);
  if (settings.overrides.lid_fraction != null) modules.length = 0;
  if (!modules.length) modules.push(["unknown", { model: "", technology: "" }]);
  async function save(patch: LossPatch) {
    if (state.busy) return;
    const updated = await run(t("losses.saving"), () => engine.updateLosses(view.bundle.project.project_id, patch));
    if (updated) dispatch({ type: "setView", view: updated });
  }
  return <div className="stack" data-loss-settings={settings.status}>
    <p><strong>{t(settings.status === "edited" ? "losses.edited" : "losses.recommended")}</strong> · {settings.defaults_id}</p>
    {settings.defaults_id === "recommended_defaults.v1" && <p>{t("losses.earlierLid")} <Button disabled={!!state.busy} onClick={() => void save({ defaults_id: "recommended_defaults.v2", overrides: {} })}>{t("losses.currentDefaults")}</Button></p>}
    <p className="note">{t("losses.fractionsNote")}</p>
    <div className="grid2">{Array.from({ length: 12 }, (_, i) => `month${i + 1}`).map((key, i) => <Field key={key} label={t("losses.month", { month: i + 1 })}>
      <input disabled={!!state.busy} className="input" type="number" min="0" max="100" step="any" value={draft[key] ?? ""} aria-invalid={errors.includes(key)} onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} />
    </Field>)}</div>
    <div className="grid2">{LOSS_FIELDS.map((key) => <Field key={key} label={t(`losses.${key.replaceAll(".", "_")}`)} hint={t(`losses.hint_${key.replaceAll(".", "_")}`)}>
      <input disabled={!!state.busy} className="input" type="number" step={key === "operating_year" ? "1" : "any"} min={key === "operating_year" ? "1" : "0"} value={draft[key] ?? ""}
        aria-invalid={errors.includes(key)} placeholder={t(key === "lid_fraction" || key.includes("mismatch") || key.endsWith("reference_power_w") ? "losses.automatic" : "losses.unspecified")}
        onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} />
      {key === "lid_fraction" && settings.defaults_id === "recommended_defaults.v2" ? <small>{modules.map(([id, module]) => {
        const lid = moduleLid(settings, module!);
        return <span className="stack" key={id}>{modules.length > 1 && module!.model ? `${module!.model}: ` : ""}{t(`losses.lid_${lid.source}`, { value: formatPercent(lid.fraction), technology: module!.technology || t("losses.unknownTechnology") })}</span>;
      })}</small> : <small>{t(settings.sources[key] === "user" ? "losses.edited" : "losses.recommended")}{["ac_wiring_nominal_fraction", "unavailability_fraction"].includes(key) && Number(draft[key]) === 0 ? ` · ${t("losses.notSet")}` : ""}</small>}
    </Field>)}</div>
    <Field label={t("losses.transformer_enabled")}><input disabled={!!state.busy} type="checkbox" checked={draft["transformer.enabled"] === "true"} onChange={(e) => setDraft({ ...draft, "transformer.enabled": String(e.target.checked) })} /></Field>
    <p className="note">{t("losses.transformerNote")}</p>
    {errors.length > 0 && <p role="alert">{t("losses.invalid", { fields: errors.map((key) => key.startsWith("month") ? t("losses.month", { month: key.slice(5) }) : t(`losses.${key.replaceAll(".", "_")}`)).join(", ") })}</p>}
    <div className="row"><Button disabled={!!state.busy || !changed || errors.length > 0} onClick={() => void save(lossFormPatch(initial, draft))}>{t("losses.save")}</Button>
      <Button disabled={!!state.busy || settings.status === "recommended_defaults"} onClick={() => void save({ reset_to_recommended_defaults: true })}>{t("losses.reset")}</Button></div>
    <CircuitLossEditor view={view} busy={!!state.busy} save={save} />
  </div>;
}

/** Always the selected run's immutable snapshot, never the current project. */
export function RunLossSettings({ run }: { run: SimulationRunRecord }) {
  const { t } = useTranslation();
  const settings = run.resolved_loss_settings ?? run.summary_result?.resolved_loss_settings;
  if (!settings) return <p>{t("losses.legacy")}</p>;
  return <details><summary>{t("losses.runSettings")} · {t(settings.status === "edited" || !!run.circuit_loss_resolution ?  "losses.edited" : "losses.recommended")}</summary>
    <p>{settings.defaults_id} · {settings.settings_sha256}</p>
    <dl>{Object.entries(lossDraft(settings)).map(([key, value]) => <div key={key}><dt>{key.startsWith("month") ? t("losses.month", { month: key.slice(5) }) : t(`losses.${key.replaceAll(".", "_")}`)}</dt><dd>{key === "transformer.enabled" ? t(value === "true" ? "losses.enabled" : "losses.disabled") : value || t(key === "transformer.copper_fraction" ? "losses.unspecified" : "losses.automatic")} · {t(settings.sources[key.startsWith("month") ? "soiling.monthly_fractions" : key] === "user" ? "losses.edited" : "losses.recommended")}</dd></div>)}</dl>
    {run.circuit_loss_resolution && <RunCircuitLosses resolution={run.circuit_loss_resolution} />}
    {(settings.inverter_reference_power_w != null || settings.inverters) && <dl>
      {settings.inverter_reference_power_w != null && <div><dt>{t("losses.inverterReference")}</dt><dd>{settings.inverter_reference_power_w} W</dd></div>}
      {Object.entries(settings.inverters ?? {}).map(([id, ref]) => <div key={id}><dt>{t("losses.inverterReference")} · {id}</dt><dd>{ref.nominal_ac_power_w} W</dd></div>)}
    </dl>}
    {settings.transformer_reference_power_w != null && <p>{t("losses.transformerReference")}: {settings.transformer_reference_power_w} W</p>}
    {settings.method === "detailed_iv_plus_dispersion_scalar" && <p>{t("losses.dispersion")}</p>}
    {settings.circuits && <table className="tbl"><caption>{t("losses.circuits")}</caption><thead><tr><th>MPPT</th><th>V (STC)</th><th>A (STC)</th><th>Ω</th><th>{t("losses.lid_fraction")}</th><th>{t("losses.module_mismatch_fraction")}</th><th>{t("losses.string_mismatch_fraction")}</th></tr></thead><tbody>{Object.entries(settings.circuits).map(([id, c]) => <tr key={id}><th>{id}</th><td>{c.reference_voltage_v == null ? t("losses.unspecified") : formatNumber(c.reference_voltage_v, 7)}</td><td>{c.reference_current_a == null ? t("losses.unspecified") : formatNumber(c.reference_current_a, 7)}</td><td>{formatNumber(c.resistance_ohm, 7)}</td><td>{c.lid_fraction == null ? formatPercent(settings.values.lid_fraction ?? 0) + " %" : t(`losses.lid_${c.lid_source}`, { value: formatPercent(c.lid_fraction), technology: c.technology || t("losses.unknownTechnology") })}</td><td>{formatPercent(c.module_mismatch_fraction)} %</td><td>{formatPercent(c.string_mismatch_fraction)} %</td></tr>)}</tbody></table>}
  </details>;
}

export interface AcSegmentDraft {
  mode: "inherit" | "percent" | "cable"; reference: "rated_ac" | "custom";
  fraction: string; power: string; length: string; area: string; material: "copper" | "aluminium"; voltage: string; temperature: string;
}
export function acSegmentDraft(segment?: AcWiringSegment): AcSegmentDraft {
  return { mode: segment?.mode ?? "inherit", reference: segment?.mode === "percent" ? segment.reference : "rated_ac",
    fraction: segment?.mode === "percent" ? String(segment.loss_fraction * 100) : "0",
    power: segment?.mode === "percent" && segment.reference === "custom" ? String(segment.reference_power_w) : "",
    length: segment?.mode === "cable" ? String(segment.length_one_way_m) : "",
    area: segment?.mode === "cable" ? String(segment.cross_section_per_phase_mm2) : "",
    material: segment?.mode === "cable" ? segment.material : "copper",
    voltage: segment?.mode === "cable" ? String(segment.line_voltage_v) : "400",
    temperature: segment?.mode === "cable" ? String(segment.conductor_temperature_c) : "50" };
}
export function acSegmentValue(draft: AcSegmentDraft): AcWiringSegment | null {
  if (draft.mode === "inherit") return null;
  if (draft.mode === "percent") return draft.reference === "rated_ac"
    ? { mode: "percent", loss_fraction: Number(draft.fraction) / 100, reference: "rated_ac" }
    : { mode: "percent", loss_fraction: Number(draft.fraction) / 100, reference: "custom", reference_power_w: Number(draft.power) };
  return { mode: "cable", length_one_way_m: Number(draft.length), cross_section_per_phase_mm2: Number(draft.area),
    material: draft.material, line_voltage_v: Number(draft.voltage), conductor_temperature_c: Number(draft.temperature), phase_system: "balanced_three_phase", power_factor: 1 };
}
export function acSegmentErrors(draft: AcSegmentDraft): string[] {
  const positive = (s: string) => !!s.trim() && Number.isFinite(Number(s)) && Number(s) > 0;
  if (draft.mode === "inherit") return [];
  if (draft.mode === "percent") return [!draft.fraction.trim() || !Number.isFinite(Number(draft.fraction)) || Number(draft.fraction) < 0 || Number(draft.fraction) >= 100 ? "fraction" : "", draft.reference === "custom" && !positive(draft.power) ? "power" : ""].filter(Boolean);
  return [!positive(draft.length) ? "length" : "", !positive(draft.area) ? "area" : "", !positive(draft.voltage) ? "voltage" : "", !draft.temperature.trim() || !Number.isFinite(Number(draft.temperature)) || Number(draft.temperature) < 0 || Number(draft.temperature) > 100 ? "temperature" : ""].filter(Boolean);
}
interface CircuitRowDraft { dc: string; quality: string; ac: AcSegmentDraft }
export interface CircuitDraft { inverters: Record<string, CircuitRowDraft>; mppts: Record<string, CircuitRowDraft>; plant: AcSegmentDraft }
export function circuitDraft(view: ProjectView): CircuitDraft {
  const stored = view.bundle.loss_settings?.overrides;
  const row = (value?: { dc_wiring_stc_fraction?: number; module_quality_fraction?: number; ac_wiring?: AcWiringSegment }): CircuitRowDraft => ({ dc: value?.dc_wiring_stc_fraction == null ? "" : String(value.dc_wiring_stc_fraction * 100), quality: value?.module_quality_fraction == null ? "" : String(value.module_quality_fraction * 100), ac: acSegmentDraft(value?.ac_wiring) });
  return { inverters: Object.fromEntries(view.bundle.electrical_design.inverter_instances.map((i) => [i.inverter_instance_id, row(stored?.circuit_overrides?.inverters?.[i.inverter_instance_id])])),
    mppts: Object.fromEntries(view.topology_view.inverters.flatMap((i) => i.mppts.map((m) => [m.mppt_instance_id, row(stored?.circuit_overrides?.mppts?.[m.mppt_instance_id])]))), plant: acSegmentDraft(stored?.plant_ac_wiring) };
}
export function circuitFormErrors(draft: CircuitDraft): string[] {
  const errors = acSegmentErrors(draft.plant).map((s) => `plant.${s}`);
  for (const [id, row] of [...Object.entries(draft.inverters), ...Object.entries(draft.mppts)]) {
    for (const key of ["dc", "quality"] as const) if (row[key].trim()) {
      const n = Number(row[key]); if (!Number.isFinite(n) || n >= 100 || (key === "dc" ? n < 0 : n <= -100)) errors.push(`${id}.${key}`);
    }
    errors.push(...acSegmentErrors(row.ac).map((s) => `${id}.${s}`));
  }
  return errors;
}
export function circuitFormPatch(view: ProjectView, draft: CircuitDraft): LossPatch {
  const stored = view.bundle.loss_settings?.overrides.circuit_overrides;
  const inverters: NonNullable<CircuitOverridePatch["inverters"]> = {};
  const mppts: NonNullable<CircuitOverridePatch["mppts"]> = {};
  let any = !!Object.keys(stored?.inverters ?? {}).find((id) => !(id in draft.inverters)) || !!Object.keys(stored?.mppts ?? {}).find((id) => !(id in draft.mppts));
  for (const [kind, rows] of [["inverters", draft.inverters], ["mppts", draft.mppts]] as const) for (const [id, row] of Object.entries(rows)) {
    const dc = row.dc.trim() ? Number(row.dc) / 100 : null, quality = row.quality.trim() ? Number(row.quality) / 100 : null;
    const ac = kind === "inverters" ? acSegmentValue(row.ac) : null;
    any ||= dc != null || quality != null || ac != null;
    if (kind === "inverters") inverters[id] = { dc_wiring_stc_fraction: dc, module_quality_fraction: quality, ac_wiring: ac };
    else mppts[id] = { dc_wiring_stc_fraction: dc, module_quality_fraction: quality };
  }
  return { overrides: { circuit_overrides: any ? { binding: { electrical_revision_id: view.bundle.electrical_design.electrical_revision_id, topology_sha256: null }, inverters, mppts } : null, plant_ac_wiring: acSegmentValue(draft.plant) } };
}
export function AcSegmentEditor({ name, draft, onChange, plant = false }: { name: string; draft: AcSegmentDraft; onChange: (draft: AcSegmentDraft) => void; plant?: boolean }) {
  const { t } = useTranslation();
  const set = (key: keyof AcSegmentDraft, value: string) => onChange({ ...draft, [key]: value });
  return <fieldset className="stack"><legend>{name}</legend>
    <Field label={`${name} · ${t("circuit.mode")}`}><select className="input" value={draft.mode} onChange={(e) => set("mode", e.target.value)}><option value="inherit">{t(plant ? "circuit.notSet" : "circuit.inherit")}</option><option value="percent">{t("circuit.percent")}</option><option value="cable">{t("circuit.cable")}</option></select></Field>
    {draft.mode === "percent" && <><Field label={`${name} · ${t("circuit.fraction")}`}><input className="input" type="number" step="any" min="0" value={draft.fraction} onChange={(e) => set("fraction", e.target.value)} /></Field>
      <Field label={`${name} · ${t("circuit.reference")}`}><select className="input" value={draft.reference} onChange={(e) => set("reference", e.target.value)}><option value="rated_ac">{t("circuit.rated")}</option><option value="custom">{t("circuit.custom")}</option></select></Field>
      {draft.reference === "custom" && <Field label={`${name} · ${t("circuit.power")}`}><input className="input" type="number" step="any" value={draft.power} onChange={(e) => set("power", e.target.value)} /></Field>}</>}
    {draft.mode === "cable" && <><p className="note">{t("circuit.cableNote")}</p><Field label={`${name} · ${t("circuit.material")}`}><select className="input" value={draft.material} onChange={(e) => set("material", e.target.value)}><option value="copper">{t("circuit.copper")}</option><option value="aluminium">{t("circuit.aluminium")}</option></select></Field>
      {(["length", "area", "voltage", "temperature"] as const).map((key) => <Field key={key} label={`${name} · ${t(`circuit.${key}`)}`}>{key === "area"
        ? <select className="input" aria-label={`${name} · ${t("circuit.area")}`} value={draft.area} onChange={(e) => set("area", e.target.value)}>
            {draft.area === "" && <option value="">{t("circuit.chooseSize")}</option>}
            {draft.area !== "" && !CABLE_SIZES_MM2.some((size) => size === Number(draft.area)) && <option value={draft.area}>{t("circuit.customSize", { value: draft.area })}</option>}
            {CABLE_SIZES_MM2.map((size) => <option key={size} value={String(size)}>{size}</option>)}
          </select>
        : <input className="input" type="number" step="any" value={draft[key]} onChange={(e) => set(key, e.target.value)} />}</Field>)}
      <p className="note">{t("circuit.temperatureAssumption")}</p></>}
  </fieldset>;
}
export function CircuitLossEditor({ view, busy, save }: { view: ProjectView; busy: boolean; save: (patch: LossPatch) => Promise<void> }) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState(() => circuitDraft(view));
  useEffect(() => setDraft(circuitDraft(view)), [view.bundle.loss_settings, view.bundle.electrical_design, view.bundle.project.project_id]);
  const initial = circuitDraft(view), changed = JSON.stringify(initial) !== JSON.stringify(draft), errors = circuitFormErrors(draft);
  const stale = !!view.loss_binding_findings?.length;
  const scalar = (kind: "inverters" | "mppts", id: string, name: string) => <div className="grid2">{(["dc", "quality"] as const).map((key) => <Field key={key} label={`${name} · ${t(`circuit.${key}`)}`} hint={t(key === "quality" ? "circuit.qualityNote" : "circuit.inherit")}><input className="input" type="number" step="any" placeholder={t("circuit.inherit")} value={draft[kind][id]?.[key] ?? ""} onChange={(e) => setDraft({ ...draft, [kind]: { ...draft[kind], [id]: { ...draft[kind][id], [key]: e.target.value } } })} /></Field>)}</div>;
  return <fieldset disabled={busy} className="stack" data-circuit-loss-editor><legend>{t("circuit.title")}</legend>
    {view.loss_binding_findings?.map((f) => <p role="alert" key={f.rule_id}>{f.message}</p>)}
    {view.bundle.electrical_design.inverter_instances.map((i) => <section className="panel-card" key={i.inverter_instance_id} data-circuit-inverter={i.inverter_instance_id}><h4>{i.name}{!i.enabled && ` · ${t("losses.disabled")}`}</h4>
      {scalar("inverters", i.inverter_instance_id, i.name)}
      <AcSegmentEditor name={t("circuit.inverterSegment", { name: i.name })} draft={draft.inverters[i.inverter_instance_id]?.ac ?? acSegmentDraft()} onChange={(ac) => setDraft({ ...draft, inverters: { ...draft.inverters, [i.inverter_instance_id]: { ...draft.inverters[i.inverter_instance_id], ac } } })} />
      <details><summary>{t("circuit.mpptOverrides")}</summary>{view.topology_view.inverters.find((v) => v.inverter_instance_id === i.inverter_instance_id)?.mppts.map((m) => <div key={m.mppt_instance_id}>{scalar("mppts", m.mppt_instance_id, `${i.name} · MPPT ${m.index}`)}</div>)}</details>
    </section>)}
    <AcSegmentEditor name={t("circuit.plantSegment")} draft={draft.plant} onChange={(plant) => setDraft({ ...draft, plant })} plant />
    {!!errors.length && <p role="alert">{t("circuit.invalid")}</p>}
    <Button disabled={busy || (!changed && !stale) || !!errors.length} onClick={() => { if (!busy && !errors.length) void save(circuitFormPatch(view, draft)); }}>{t(stale ? "circuit.rebind" : "circuit.save")}</Button>
  </fieldset>;
}
export function RunCircuitLosses({ resolution }: { resolution: CircuitLossResolution }) {
  const { t } = useTranslation();
  const segment = (name: string, value: NonNullable<CircuitLossResolution["plant_ac_wiring"]>) => <div key={name}><dt>{name}</dt><dd>{t(value.mode === "cable" ? "circuit.cable" : "circuit.percent")} · {t("circuit.power")}: {formatNumber(value.reference_power_w)} W{value.mode === "percent" ? ` · ${formatPercent(value.loss_fraction)} %` : ` · ${value.length_one_way_m} m / ${value.cross_section_per_phase_mm2} mm² · ${value.line_voltage_v} V · ${value.conductor_temperature_c} °C · ρ20=${value.resistivity_20_ohm_mm2_m}, α=${value.temperature_coefficient_per_c}, ρ(T)=${value.resistivity_ohm_mm2_m}, R=${value.resistance_per_phase_ohm} Ω`}</dd></div>;
  return <section data-run-circuit-losses><h4>{t("circuit.recorded")}</h4><table className="tbl"><thead><tr><th>MPPT</th><th>{t("circuit.dc")}</th><th>{t("circuit.quality")}</th><th>V / A / Ω</th></tr></thead><tbody>{Object.entries(resolution.circuits).map(([id, c]) => <tr key={id}><th>{resolution.inverters[c.inverter_instance_id]?.name} · MPPT {c.mppt_index}</th><td>{formatPercent(c.dc_wiring_stc_fraction)} % · {t(`circuit.source_${c.dc_wiring_source}`, { defaultValue: c.dc_wiring_source })}</td><td>{[...new Set(Object.values(c.module_quality_by_module))].map((q) => `${formatPercent(q)} %`).join(", ")} · {[...new Set(Object.values(c.module_quality_sources))].map((s) => t(`circuit.source_${s}`, { defaultValue: s })).join(", ")}</td><td>{c.reference_voltage_v ?? "—"} / {c.reference_current_a ?? "—"} / {c.resistance_ohm ?? "—"}</td></tr>)}</tbody></table>
    <dl>{Object.values(resolution.inverters).map((i) => segment(t("circuit.inverterSegment", { name: i.name }), i.ac_wiring))}{resolution.plant_ac_wiring && segment(t("circuit.plantSegment"), resolution.plant_ac_wiring)}</dl>
  </section>;
}
