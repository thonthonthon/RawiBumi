import { fieldSupportIds } from "./types";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ModalDialog } from "./ui/ModalDialog";
import { uiStore, useStore } from "./state/store";
import { useEntityEdits } from "./canvas/useEntityEdits";
import { moduleDeletion, cancelModuleDelete, confirmModuleDelete, moduleFill, cancelModuleFill, confirmModuleFill, moduleReasonText } from "./canvas/useModuleEdits";
import { dependentFields, dependentFieldsBlocked, cancelDependentFields, confirmDependentFields, sceneRefusal, cancelSceneRefusal, confirmSceneRefusal } from "./state/history";
import { Button, NotWired } from "./ui/kit";
import { engine } from "./client";
import type { TFunction } from "i18next";
import type { WeatherImportPreview, ComponentLibraryReason, ComponentCompletionInput, ComponentLibraryEntry, ComponentLibraryPreview } from "./types";


const CATEGORIES = [
  { id: "components", formats: ".PAN, .OND", accept: ".pan,.ond" },
  { id: "meteo", formats: "TMY3, EPW, Meteonorm DAT, PVsyst standard CSV, native CSV", accept: ".epw,.csv,.dat,.tm3,.tmy,.met" },
  { id: "geometry", formats: "SketchUp COLLADA (.dae), PVsyst .SHD, glTF/GLB, OBJ", accept: ".dae,.shd,.glb,.gltf,.obj" },
  { id: "horizon", formats: "CSV azimuth/elevation, PVsyst .HOR", accept: ".csv,.hor" },
  { id: "load", formats: "CSV timestamp, value", accept: ".csv,.txt" }
];


const COMPLETION_REASON_CODES = new Set(["mppt_operating_current_missing", "basic_design_incomplete_due_to_mppt",
  "basic_design_not_ready", "efficiency_curve_unavailable", "module_sdm_not_ready"]);
export function componentReasonText(reason: ComponentLibraryReason, language: string, t: TFunction): string {
  return language.startsWith("id") && COMPLETION_REASON_CODES.has(reason.code)
    ? t(`s12a2.reasons.${reason.code}`, { rule_ids: reason.rule_ids?.join(", ") }) : reason.message;
}

export function completionInput(values: Record<string, string>, source: {document: string; page_or_section: string; url: string}, base: ComponentLibraryPreview): ComponentCompletionInput | null {
  const fields: Record<string, number> = {};
  for (const field of base.completion_fields ?? []) {
    const raw = values[field.path]?.trim();
    if (!raw) continue;
    const value = Number(raw);
    if (!Number.isFinite(value) || value <= 0 || value > field.max || (field.unit === "Hz" && value !== 50 && value !== 60)) return null;
    fields[field.path] = value;
  }
  if (!Object.keys(fields).length || !source.document.trim() || source.document.trim().length > 200 || !source.page_or_section.trim() || source.page_or_section.trim().length > 100) return null;
  if (source.url.trim()) {
    try { const url = new URL(source.url.trim()); if (!["https:", "http:"].includes(url.protocol)) return null; } catch { return null; }
  }
  const operating = fields["mppt_template.max_operating_current_a"] ?? base.parameters.mppt_max_operating_current_a;
  const short = fields["mppt_template.max_short_circuit_current_a"];
  if (typeof operating === "number" && short !== undefined && short < operating) return null;
  return { fields, source: { document: source.document.trim(), page_or_section: source.page_or_section.trim(), ...(source.url.trim() ? {url: source.url.trim()} : {}) } };
}

export function DatasheetCompletion({ base, onClose, onSaved }: {base: ComponentLibraryPreview; onClose: () => void; onSaved: (entry: ComponentLibraryPreview) => Promise<void>}) {
  const {t, i18n} = useTranslation();
  const {state, run} = useStore();
  const [values, setValues] = useState<Record<string, string>>({});
  const [source, setSource] = useState({document: "", page_or_section: "", url: ""});
  const [result, setResult] = useState<ComponentLibraryPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const busy = !!state.busy;
  const input = completionInput(values, source, base);
  async function execute(save: boolean) {
    if (busy || !input || (save && !result)) return;
    setError(null);
    await run(t(save ? "s12a2.save" : "s12a2.preview"), async () => {
      try {
        if (save) { const saved = await engine.completeComponent(base.revision_id, input); await onSaved(saved.entry); }
        else setResult(await engine.previewComponentCompletion(base.revision_id, input));
      } catch (err) { setError(err instanceof Error ? err.message : String(err)); throw err; }
    });
  }
  return <ModalDialog label={t("s12a2.title")} onClose={() => { if (!busy) onClose(); }} small>
    <header className="modal__head"><h2>{t("s12a2.title")}</h2></header>
    <div className="modal__body"><p>{base.manufacturer} {base.model} · <code>{base.revision_id}</code></p>
      <p className="note">{t("s12a2.note")}</p>
      {(base.completion_fields ?? []).map(field => <label className="field" key={field.path}>{t(`s12a2.fields.${field.path.split(".").at(-1)}`)} ({field.unit})
        <input type="number" min={field.unit === "Hz" ? 50 : 0} max={field.max} step={field.unit === "Hz" ? 10 : "any"} disabled={busy}
          value={values[field.path] ?? ""} onChange={e => { setValues({...values, [field.path]: e.target.value}); setResult(null); }} />
      </label>)}
      {(["document", "page_or_section", "url"] as const).map(key => <label className="field" key={key}>{t(`s12a2.${key}`)}
        <input type={key === "url" ? "url" : "text"} required={key !== "url"} maxLength={key === "document" ? 200 : key === "page_or_section" ? 100 : undefined} disabled={busy}
          value={source[key]} onChange={e => { setSource({...source, [key]: e.target.value}); setResult(null); }} />
      </label>)}
      {!input && <p className="note" role="status">{t("s12a2.required")}</p>}
      {error && <p role="alert" className="note note--warn">{error}</p>}
      {result && <section aria-label={t("s12a2.result")}>
        <p data-component-readiness>{t(result.simulation_ready ? "s12a.ready" : "s12a.layoutOnly")}</p>
        <ul>{result.reasons.map((reason, i) => <li key={i}>{componentReasonText(reason, i18n.language, t)}</li>)}</ul>
        <ul>{result.completed_fields?.map(field => <li key={field.path}>{t(`s12a2.fields.${field.path.split(".").at(-1)}`)}: {field.value} {field.unit} · {field.source.document}, {field.source.page_or_section}{field.source.url && ` · ${field.source.url}`}</li>)}</ul>
      </section>}
      <div className="row"><Button disabled={busy || !input} onClick={() => void execute(false)}>{t("s12a2.preview")}</Button>
        {result && <Button tone="primary" disabled={busy || !input} onClick={() => void execute(true)}>{t("s12a2.save")}</Button>}
        <Button cancel disabled={busy} onClick={onClose}>{t("hardening.cancel")}</Button></div>
    </div>
  </ModalDialog>;
}

export function canUseWeather(preview: WeatherImportPreview, accepted: boolean): boolean {
  return preview.qc.status !== "failed" && !preview.qc.findings.some(f => ["error", "blocking_error"].includes(f.severity)) &&
    (!preview.requires_accept_distant_location || accepted);
}

export function WeatherFilePreview({preview: p, busy, accepted, committed, onAccept, onCommit}: {
  preview: WeatherImportPreview; busy: boolean; accepted: boolean; committed: boolean; onAccept: (accepted: boolean) => void; onCommit: () => void;
}) {
  const {t, i18n} = useTranslation();
  const number = (value: number | null | undefined) => value == null ? t("s12b.unavailable") : new Intl.NumberFormat(i18n.language, {maximumFractionDigits: 3}).format(value);
  const warningText = (warning: WeatherImportPreview["warnings"][number]) => i18n.language.startsWith("id") && i18n.exists(`s12b.warnings.${warning.code}`)
    ? t(`s12b.warnings.${warning.code}`, {distance: number(warning.distance_km), difference: number(warning.difference_m)}) : warning.message;
  return <section aria-label={t("s12b.preview")}>
    <h3>{p.filename} · {p.format}</h3>
    <dl><dt>{t("s12b.fileLocation")}</dt><dd>{number(p.location?.latitude_deg)}, {number(p.location?.longitude_deg)} · {number(p.location?.elevation_m)} m</dd>
      <dt>{t("s12b.siteLocation")}</dt><dd>{number(p.site.latitude_deg)}, {number(p.site.longitude_deg)} · {number(p.site.elevation_m)} m</dd>
      <dt>{t("s12b.distance")}</dt><dd>{number(p.distance_km)} km</dd>
      <dt>{t("s12b.period")}</dt><dd>{p.period.start} → {p.period.end}</dd>
      <dt>{t("s12b.step")}</dt><dd>{number(p.step_minutes)} min · {number(p.row_count)} {t("s12b.rows")}</dd>
      <dt>{t("s12b.typical")}</dt><dd>{t(p.typical_year ? "s12b.yes" : "s12b.no")}</dd>
      <dt>{t("s12b.sourceZone")}</dt><dd>{p.time_zone.source_timezone} · {number(p.time_zone.source_utc_offset_hours)} h</dd>
      <dt>{t("s12b.siteZone")}</dt><dd>{p.time_zone.site_timezone} · {number(p.time_zone.site_standard_utc_offset_hours)} h</dd>
      <dt>{t("s12b.canonicalZone")}</dt><dd>{p.time_zone.canonical_timezone}</dd>
      <dt>{t("s12b.variables")}</dt><dd>{p.variables.join(", ")}</dd>
    </dl>
    <table className="tbl" aria-label={t("s12b.monthly")}><thead><tr><th>{t("s12b.month")}</th><th>GHI (kWh/m²)</th></tr></thead>
      <tbody>{p.monthly_ghi_kwh_m2.map((value, i) => <tr key={i}><th scope="row">{new Intl.DateTimeFormat(i18n.language, {month: "short", timeZone: "UTC"}).format(new Date(Date.UTC(2001, i, 1)))}</th><td>{number(value)}</td></tr>)}</tbody>
      <tfoot><tr><th scope="row">{t("s12b.total")}</th><td>{number(p.annual_ghi_kwh_m2)}</td></tr></tfoot>
    </table>
    <p>{t("s12b.qc")}: {p.qc.status}</p>
    <ul>{p.qc.findings.map((finding, i) => <li key={i} data-rule-id={finding.rule_id}>{finding.severity}: {finding.message}</li>)}</ul>
    <ul>{p.warnings.map((warning, i) => <li key={i} data-weather-warning={warning.code}>{warningText(warning)}</li>)}</ul>
    {p.requires_accept_distant_location && <label className="check"><input type="checkbox" checked={accepted} disabled={busy || committed} onChange={e => onAccept(e.target.checked)} />{t("s12b.acceptDistance")}</label>}
    <Button tone="primary" disabled={busy || committed || !canUseWeather(p, accepted)} onClick={() => {if (!busy && !committed && canUseWeather(p, accepted)) onCommit();}}>{t("s12b.use")}</Button>
  </section>;
}

export function ImportHub({ onClose, initial = "components" }: { onClose: () => void; initial?: string }) {
  const { t, i18n } = useTranslation();
  const { state, run, dispatch, toast } = useStore();
  const [cat, setCat] = useState(initial);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ComponentLibraryPreview | null>(null);
  const [entries, setEntries] = useState<ComponentLibraryEntry[]>([]);
  const [showHidden, setShowHidden] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hide, setHide] = useState<ComponentLibraryEntry | null>(null);
  const [imported, setImported] = useState(false);
  const [completion, setCompletion] = useState<ComponentLibraryPreview | null>(null);
  const [weatherPreview, setWeatherPreview] = useState<WeatherImportPreview | null>(null);
  const [acceptDistance, setAcceptDistance] = useState(false);
  const c = CATEGORIES.find((x) => x.id === cat) ?? CATEGORIES[0];
  const busy = !!state.busy;
  const close = () => { if (!busy) onClose(); };
  const failure = (err: unknown) => { setError(err instanceof Error ? err.message : String(err)); throw err; };
  useEffect(() => {
    if (cat !== "components") return;
    let active = true;
    // Read-only loading must survive remounts without competing for the edit guard.
    void engine.componentLibrary(showHidden).then((result) => {
      if (active) { setEntries(result); setError(null); }
    }).catch((err: unknown) => {
      if (active) {
        const message = err instanceof Error ? err.message : String(err);
        setError(message); toast("error", message);
      }
    });
    return () => { active = false; };
  }, [cat, showHidden, toast]);
  async function refresh() {
    setEntries(await engine.componentLibrary(showHidden));
    const pid = state.view?.bundle.project.project_id;
    if (pid) {
      const view = await engine.project(pid);
      if (uiStore.getState().state.view?.bundle.project.project_id === pid) dispatch({ type: "setView", view });
    }
  }
  async function detect() {
    if (!file || busy || !["components", "meteo"].includes(cat)) return;
    if (cat === "meteo") {
      const pid = state.view?.bundle.project.project_id;
      if (!pid) return;
      setError(null); setWeatherPreview(null); setAcceptDistance(false); setImported(false);
      if (file.size > 50 * 1024 * 1024) {setError(t("s12b.tooLarge")); return;}
      const result = await run(t("hardening.detectPreview"), async () => {
        try {return await engine.previewWeatherFile(pid, file);} catch (err) {return failure(err);}
      });
      if (result) setWeatherPreview(result);
      return;
    }
    setError(null); setPreview(null); setImported(false);
    const result = await run(t("hardening.detectPreview"), async () => {
      try { return await engine.previewComponent(file); } catch (err) { return failure(err); }
    });
    if (result) setPreview(result);
  }
  async function commit() {
    if (!file || !preview?.schema_ready || imported || busy) return;
    setError(null);
    await run(t("s12a.import"), async () => {
      try {
        const result = await engine.importComponent(file);
        setPreview(result.entry); setImported(true);
        await refresh();
        toast("ok", t("s12a.imported", { revision: result.entry.revision_id }));
      } catch (err) { failure(err); }
    });
  }
  async function useWeather() {
    const pid = state.view?.bundle.project.project_id;
    if (!pid || !file || !weatherPreview || busy || imported || !canUseWeather(weatherPreview, acceptDistance)) return;
    await run(t("s12b.use"), async () => {
      try {
        const result = await engine.importWeatherFile(pid, file, acceptDistance);
        const view = await engine.project(pid);
        if (uiStore.getState().state.view?.bundle.project.project_id === pid) dispatch({type: "setView", view});
        setImported(true); setError(null);
        toast("ok", t("s12b.imported", {dataset: result.selection.name ?? result.selection.revision_id}));
      } catch (err) {failure(err);}
    });
  }
  async function visibility(entry: ComponentLibraryEntry, hidden: boolean) {
    if (busy) return;
    await run(t(hidden ? "s12a.hide" : "s12a.unhide"), async () => {
      try {
        if (hidden) await engine.hideComponent(entry.definition.revision_id);
        else await engine.unhideComponent(entry.definition.revision_id);
        await refresh(); setHide(null); setError(null);
      } catch (err) { failure(err); }
    });
  }
  const units: Record<string, string> = {
    pmp_w: "W", voc_v: "V", isc_a: "A", vmp_v: "V", imp_a: "A", width_m: "m", height_m: "m",
    cell_count: t("s12a.cells"), gamma_pmp_pct_per_c: "%/°C", mu_voc_v_per_c: "V/°C", technology: "—",
    nominal_ac_power_w: "W", max_dc_power_w: "W", mppt_count: "MPPT", mppt_v_min: "V", mppt_v_max: "V",
    max_dc_voltage_v: "V", max_input_current_a: "A", mppt_max_operating_current_a: "A", efficiency_fraction: "%"
  };
  return (
    <ModalDialog label={t("hardening.importTitle")} onClose={close}>
      <header className="modal__head">
        <h2>{t("hardening.importTitle")}</h2>
        <button className="iconbtn" type="button" disabled={busy} onClick={close} aria-label={t("hardening.close")}>✕</button>
      </header>
      <div className="modal__body import">
        <nav className="import__nav" aria-label={t("hardening.importCategories")}>
          {CATEGORIES.map((x) => <button key={x.id} type="button" disabled={busy} aria-current={x.id === cat ? "true" : undefined}
            className={x.id === cat ? "import__cat import__cat--on" : "import__cat"}
            onClick={() => { setCat(x.id); setFile(null); setPreview(null); setImported(false); setError(null); setWeatherPreview(null); setAcceptDistance(false); }}>
            {t(`hardening.import_${x.id}`)}
          </button>)}
        </nav>
        <div className="import__main">
          <div className="import__formats">{c.formats}</div>
          <p className="note">{t(`hardening.note_${c.id}`)}</p>
          <label className="dropzone">
            <input type="file" disabled={busy} aria-label={t("hardening.chooseFile")} accept={c.accept}
              onChange={(e) => { setFile(e.target.files?.[0] ?? null); setPreview(null); setImported(false); setError(null); setWeatherPreview(null); setAcceptDistance(false); }} />
            {file ? <span><strong>{file.name}</strong> · {new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 1 }).format(file.size / 1024)} kB</span> : <span>{t("hardening.chooseFile")}</span>}
          </label>
          <ol className="import__steps">
            <li>{t("hardening.detect")}</li><li>{t("hardening.mapping")}</li><li>{t("hardening.provenance")}</li><li>{t("hardening.commit")}</li>
          </ol>
          <div className="row">
            <Button tone="primary" disabled={busy || !file || !["components", "meteo"].includes(cat) || (cat === "meteo" && !state.view)} onClick={() => void detect()}>{t("hardening.detectPreview")}</Button>
            {!["components", "meteo"].includes(cat) && <NotWired id="importFile" />}
          </div>
          {error && ["components", "meteo"].includes(cat) && <p className="note note--warn" role="alert">{error}</p>}
          {cat === "meteo" && weatherPreview && <WeatherFilePreview preview={weatherPreview} busy={busy} accepted={acceptDistance} committed={imported} onAccept={setAcceptDistance} onCommit={() => void useWeather()} />}
          {cat === "components" && <>
            {preview && <section aria-label={t("s12a.preview")}>
              <h3>{preview.manufacturer} {preview.model}</h3>
              <p>{t(preview.kind === "modules" ? "s12a.module" : "s12a.inverter")} · <code>{preview.revision_id}</code></p>
              <p className={preview.simulation_ready ? "note" : "note note--warn"} data-component-readiness>
                {t(preview.simulation_ready ? "s12a.ready" : "s12a.layoutOnly")}
              </p>
              {preview.reasons.length > 0 && <ul>{preview.reasons.map((reason, index) => <li key={index}>{componentReasonText(reason, i18n.language, t)}</li>)}</ul>}
              {preview.duplicate_of && <p className="note">{t("s12a.duplicate", { revision: preview.duplicate_of })}</p>}
              {preview.remapped_from && <p className="note">{t("s12a.remapped", { revision: preview.remapped_from })}</p>}
              <table className="tbl" aria-label={t("s12a.parameters")}>
                <thead><tr><th scope="col">{t("s12a.parameter")}</th><th scope="col">{t("s12a.value")}</th><th scope="col">{t("s12a.unit")}</th></tr></thead>
                <tbody>{Object.entries(preview.parameters).filter(([key]) => key !== "efficiency_metric").map(([key, value]) => {
                  const label = key === "efficiency_fraction" ? `s12a.params.efficiency_${preview.parameters.efficiency_metric ?? "fraction"}` : `s12a.params.${key}`;
                  const shown = value == null ? `— (${t("s12a.notInFile")})` : typeof value === "number"
                    ? new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 6 }).format(key === "efficiency_fraction" ? value * 100 : value) : value;
                  return <tr key={key}><th scope="row">{t(label)}</th><td>{shown}</td><td>{units[key] ?? "—"}</td></tr>;
                })}</tbody>
              </table>
              {[...preview.findings, ...preview.readiness_findings].length > 0 && <ul aria-label={t("s12a.findings")}>
                {[...preview.findings, ...preview.readiness_findings].map((finding, index) => <li key={index} data-rule-id={finding.rule_id}>{finding.message}</li>)}
              </ul>}
              {!preview.schema_ready && <p className="note note--warn">{t("s12a.incomplete")}</p>}
              {preview.schema_ready && !imported && <Button tone="primary" disabled={busy} onClick={() => void commit()}>{t("s12a.import")}</Button>}
            </section>}
            {preview && !preview.simulation_ready && !!preview.completion_fields?.length && <>
              <Button disabled={busy || (!imported && !preview.duplicate_of)} onClick={() => setCompletion(preview)}>{t("s12a2.title")}</Button>
              {!imported && !preview.duplicate_of && <p className="note">{t("s12a2.importFirst")}</p>}
            </>}
            <section aria-label={t("s12a.library")}>
              <h3>{t("s12a.library")}</h3>
              <label className="check"><input type="checkbox" checked={showHidden} disabled={busy} onChange={(e) => setShowHidden(e.target.checked)} />{t("s12a.showHidden")}</label>
              {!entries.length && <p className="sub">{t("s12a.empty")}</p>}
              {entries.map((entry) => <div className="card-row" key={entry.definition.revision_id}>
                <div><strong>{entry.definition.manufacturer} {entry.definition.model}</strong>
                  <div className="sub"><code>{entry.definition.revision_id}</code> · {entry.library.source_filename}</div>
                  <div>{t(entry.library.readiness.ready ? "s12a.ready" : "s12a.layoutOnly")}{entry.library.hidden && ` · ${t("s12a.hidden")}`}</div>
                </div>
                {!entry.library.readiness.ready && !!entry.completion_preview?.completion_fields?.length && <Button disabled={busy} onClick={() => setCompletion(entry.completion_preview!)}>{t("s12a2.title")}</Button>}
                <Button disabled={busy} onClick={() => entry.library.hidden ? void visibility(entry, false) : setHide(entry)}>{t(entry.library.hidden ? "s12a.unhide" : "s12a.hide")}</Button>
              </div>)}
            </section>
          </>}
        </div>
      </div>
      {completion && <DatasheetCompletion key={completion.revision_id} base={completion} onClose={() => setCompletion(null)} onSaved={async entry => {
        await refresh(); setPreview(entry); setImported(true); setCompletion(null); setError(null);
        toast("ok", t("s12a2.saved", {revision: entry.revision_id}));
      }} />}
      {hide && <ModalDialog label={t("s12a.confirmHide")} onClose={() => { if (!busy) setHide(null); }} alert small>
        <header className="modal__head"><h2>{t("s12a.confirmHide")}</h2></header>
        <div className="modal__body"><p>{t("s12a.hideNote", { revision: hide.definition.revision_id })}</p>
          <div className="row"><Button disabled={busy} onClick={() => void visibility(hide, true)}>{t("s12a.hide")}</Button>
            <Button cancel disabled={busy} onClick={() => setHide(null)}>{t("hardening.cancel")}</Button></div>
        </div>
      </ModalDialog>}
    </ModalDialog>
  );
}


export function DeleteDialog() {
  return <><EntityDeleteDialog /><DependentFieldsDialog /><ObstacleConflictDialog /><ModuleDeleteDialog /><ModuleFillDialog /></>;
}

function ModuleFillDialog() {
  const { t } = useTranslation();
  const pending = moduleFill((s) => s.pending);
  const { state } = useStore();
  if (!pending) return null;
  const preview = pending.preview;
  return <ModalDialog label={t("s13c.title")} onClose={cancelModuleFill} alert>
    <header className="modal__head"><h2>{t("s13c.title")}</h2></header>
    <div className="modal__body">
      {pending.reasons.map((reason, i) => <p key={i}>{moduleReasonText(reason)}</p>)}
      {preview && <>
        <p>{t("s13c.counts", { placed: preview.placed_count, total: pending.ids.length, removed: preview.removed_count })}</p>
        <p>{t("s7a.powers", { before: (preview.stc_power_w_before / 1000).toFixed(2), after: (preview.stc_power_w_after / 1000).toFixed(2) })}</p>
        <p>{t("s13c.placed", { ids: preview.placed_ids.join(", ") })}</p>
        <p>{t("s13c.removed", { ids: preview.removed_ids.join(", ") || t("s13b.none") })}</p>
        <p>{t("s13b.strings", { ids: preview.string_ids.join(", ") || t("s13b.none") })}</p>
        <p>{t("s13c.note")}</p>
      </>}
      <div className="row">
        {preview && <Button tone="danger" disabled={!!state.busy} onClick={() => void confirmModuleFill()}>{t("s13c.confirm")}</Button>}
        <Button cancel tone="ghost" disabled={!!state.busy} onClick={cancelModuleFill}>{t("hardening.cancel")}</Button>
      </div>
    </div>
  </ModalDialog>;
}

function ModuleDeleteDialog() {
  const { t } = useTranslation();
  const pending = moduleDeletion((s) => s.pending);
  const { state } = useStore();
  if (!pending) return null;
  return <ModalDialog label={t("s13b.deleteTitle")} onClose={cancelModuleDelete} alert>
    <header className="modal__head"><h2>{t("s13b.deleteTitle")}</h2></header>
    <div className="modal__body">
      {pending.preview.fields.map((field) => <section key={field.pv_field_id} aria-label={field.name}>
        <h3>{field.name}</h3>
        <p>{t("s7a.counts", { before: field.module_count_before, after: field.module_count_after })}</p>
        <p>{t("s7a.powers", { before: (field.stc_power_w_before / 1000).toFixed(2), after: (field.stc_power_w_after / 1000).toFixed(2) })}</p>
        <p>{t("s13b.strings", { ids: field.string_ids.length ? field.string_ids.join(", ") : t("s13b.none") })}</p>
        {field.field_becomes_empty && <p className="note">{t("s13b.empty")}</p>}
      </section>)}
      <p>{t("s13b.confirmNote")}</p>
      <div className="row">
        <Button tone="danger" disabled={!!state.busy} onClick={() => void confirmModuleDelete()}>{t("s13b.confirm")}</Button>
        <Button cancel tone="ghost" disabled={!!state.busy} onClick={cancelModuleDelete}>{t("hardening.cancel")}</Button>
      </div>
    </div>
  </ModalDialog>;
}

function EntityDeleteDialog() {
  const { t } = useTranslation();
  const { state } = useStore();
  const { deleteEntities } = useEntityEdits();
  const [ids, setIds] = useState<string[]>([]);
  useEffect(() => {
    const h = (event: Event) => {
      const detail = (event as CustomEvent<string | string[]>).detail;
      const selection = uiStore.getState().state.selection;
      setIds(Array.isArray(detail) ? detail : selection.includes(detail) ? selection : [detail]);
    };
    window.addEventListener("rawibumi:delete-request", h);
    return () => window.removeEventListener("rawibumi:delete-request", h);
  }, []);
  const entities = state.entities.filter((entity) => ids.includes(entity.id));
  const skippedLocked = state.entities.filter((entity) => entity.locked && state.selection.includes(entity.id) && !ids.includes(entity.id));
  if (!entities.length) return null;
  const name = entities.map((e) => e.name).join(", ");
  const blocked = entities.some((e) => e.source === "engine" && e.modified);
  const fields = state.view!.bundle.scene.pv_fields.filter((f) => entities.some((e) => e.source === "engine" && fieldSupportIds(f).includes(e.id)));
  const close = () => setIds([]);
  const doDelete = async () => { await deleteEntities(entities); close(); };
  return <ModalDialog key="entity-delete" label={t("hardening.deleteTitle", { name })} onClose={close} small alert>
    <header className="modal__head"><h2>{t("hardening.deleteTitle", { name })}</h2></header>
    <div className="modal__body">
      <p>{t(entities.every((e) => e.source === "draft") ? "hardening.deleteDraft" : "hardening.deleteEngine", { name })}</p>
      {skippedLocked.length > 0 && <p>{t("s13a.lockedSkipped", { count: skippedLocked.length, names: skippedLocked.map((e) => e.name).join(", ") })}</p>}
      {fields.length > 0 && <p>{fields.map((field) => field.name).join(", ")}</p>}
      {blocked && <p>{t("s7b.discardReason")}</p>}
      <div className="row">
        <Button tone="danger" disabled={blocked || !!state.busy} title={blocked ? t("s7b.discardReason") : undefined} onClick={() => void doDelete()}>{fields.length ? t("s9.deleteRoof", { count: fields.length }) : t("hardening.delete")}</Button>
        <Button cancel tone="ghost" onClick={close}>{t("hardening.cancel")}</Button>
      </div>
    </div>
  </ModalDialog>;
}

export function DependentFieldsDialog() {
  const { t } = useTranslation();
  const pending = dependentFields((state) => state.pending);
  const { state } = useStore();
  if (!pending) return null;
  return <ModalDialog label={t("s9.title")} onClose={cancelDependentFields} alert>
    <header className="modal__head"><h2>{t("s9.title")}</h2></header>
    <div className="modal__body">
      {pending.message && <p role="alert">{pending.message}</p>}
      {pending.fields.map((field) => <section key={field.pv_field_id} aria-label={field.name}>
        <h3>{field.name} · {t(field.action === "delete" ? "s9.deleteAction" : "s9.refillAction")}</h3>
        <p>{t("s7a.counts", { before: field.module_count_before, after: field.module_count_after })}</p>
        <p>{t("s7a.powers", { before: (field.stc_power_w_before / 1000).toFixed(2), after: (field.stc_power_w_after / 1000).toFixed(2) })}</p>
        <p>{field.string_ids.length ? t("s7a.strings", { strings: field.string_ids.join(", ") }) : t("s7a.noStrings")}</p>
        {field.requires_discard_manual_layout && <p>{t("s7a.manual")}</p>}
        {field.action === "refill" && !field.module_count_after && <p role="alert">{t("s9.empty")}</p>}
        {field.conflicts.length > 0 && <ul>{field.conflicts.map((conflict, index) => <li key={index}>{JSON.stringify(conflict)}</li>)}</ul>}
      </section>)}
      <p>{t("s9.confirmNote")}</p>
      <div className="row">
        <Button tone="danger" disabled={!!state.busy || dependentFieldsBlocked(pending.fields)} onClick={() => void confirmDependentFields()}>{t("s9.confirm")}</Button>
        <Button cancel disabled={!!state.busy} onClick={cancelDependentFields}>{t("hardening.cancel")}</Button>
      </div>
    </div>
  </ModalDialog>;
}


export function ObstacleConflictDialog() {
  const { t } = useTranslation();
  const pending = sceneRefusal((s) => s.pending);
  const { state } = useStore();
  if (!pending) return null;
  const { detail } = pending;
  const options = detail.options;
  const keepout = detail.conflicts.some((conflict) => conflict.code === "module_exclusion_overlap");
  const title = t(options ? (keepout ? "s11a.keepoutConflict" : "s7b.obstacleConflict") : "s7b.geometryRefused");
  const removeLabel = t(keepout ? "s11a.removeModules" : "s7b.removeModules");
  const refillLabel = t(keepout ? "s11a.refillField" : "s7b.refillField");
  return <ModalDialog label={title} onClose={cancelSceneRefusal} alert>
    <header className="modal__head"><h2>{title}</h2></header>
    <div className="modal__body">
      {detail.message && <p>{detail.message}</p>}
      {options ? <>
        <section aria-label={removeLabel}>
          <h3>{removeLabel}</h3>
          <p>{t("s7b.moduleImpact", { count: options.remove_modules.module_count, kwp: (options.remove_modules.stc_power_w / 1000).toFixed(2) })}</p>
          <p>{options.remove_modules.string_ids.length ? t("s7a.strings", { strings: options.remove_modules.string_ids.join(", ") }) : t("s7a.noStrings")}</p>
          <Button tone="danger" disabled={!!state.busy} onClick={() => void confirmSceneRefusal("remove_modules")}>{removeLabel}</Button>
        </section>
        <section aria-label={refillLabel}>
          <h3>{refillLabel}</h3>
          {(options.refill_field.fields ?? []).map((field) => <div key={field.pv_field_id}>
            <p>{field.pv_field_id}</p>
            <p>{t("s7a.counts", { before: field.module_count_before, after: field.module_count_after })}</p>
            <p>{t("s7a.powers", { before: (field.stc_power_w_before / 1000).toFixed(2), after: (field.stc_power_w_after / 1000).toFixed(2) })}</p>
          </div>)}
          <p>{options.refill_field.string_ids?.length ? t("s7a.strings", { strings: options.refill_field.string_ids.join(", ") }) : t("s7a.noStrings")}</p>
          {options.refill_field.requires_discard_manual_layout && <p>{t("s7a.manual")}</p>}
          {!options.refill_field.available && <p>{options.refill_field.message ?? options.refill_field.reason}</p>}
          <Button tone="danger" disabled={!!state.busy || !options.refill_field.available} onClick={() => void confirmSceneRefusal("refill_field")}>{refillLabel}</Button>
        </section>
      </> : <ul>{detail.conflicts.map((conflict, i) => <li key={i}>{Object.entries(conflict).map(([key, value]) => `${key}: ${typeof value === "object" ? JSON.stringify(value) : String(value)}`).join(" · ")}</li>)}</ul>}
      <p><Button cancel onClick={cancelSceneRefusal}>{t(options ? (keepout ? "s11a.cancelKeepout" : "s7b.cancelObstacle") : "hardening.close")}</Button></p>
    </div>
  </ModalDialog>;
}


export function Toasts() {
  const { t } = useTranslation();
  const { state, dispatch } = useStore();
  useEffect(() => {
    const notice = state.toasts.find((n) => n.tone === "ok" || n.tone === "info");
    if (!notice) return;
    const t = setTimeout(() => dispatch({ type: "dismissToast", id: notice.id }), 6000);
    return () => clearTimeout(t);
  }, [state.toasts, dispatch]);
  return (
    <div className="toasts" aria-live="polite">
      {state.toasts.map((notice) => (
        <div key={notice.id} className={`toast toast--${notice.tone}`}>
          <span>{notice.text}</span>
          <button type="button" className="iconbtn" onClick={() => dispatch({ type: "dismissToast", id: notice.id })} aria-label={t("hardening.dismiss")}>
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
