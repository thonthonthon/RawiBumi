import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { DEMO, exportAPI, type CSVExportSchema } from "../client";
import { ExportProjectDialog } from "../project/ProjectFiles";
import { can } from "../platform/entitlements";
import { useStore } from "../state/store";
import { Button, Check, Field, Select } from "../ui/kit";
import { captureReportPlan } from "../report/build";
import { figureOverlayLoaded } from "../imagery/overlayImage";
import { ReportPanelWithPxx } from "../report/ReportPanel";

export function FreeCSVExport({ projectId, runId }: { projectId: string; runId: string }) {
  const { t } = useTranslation();
  const allowed = can("export.csv.basic");
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [downloaded, setDownloaded] = useState(false);
  const active = useRef(true), inFlight = useRef(false);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  async function download() {
    if (DEMO || !can("export.csv.basic") || inFlight.current) return;
    inFlight.current = true; setDownloading(true); setError(null); setDownloaded(false);
    try {
      const blob = await exportAPI.freeCSV(projectId, runId);
      if (!active.current) return;
      const url = URL.createObjectURL(blob), anchor = document.createElement("a");
      try {
        anchor.href = url; anchor.download = "RawiBumi_free_csv.zip";
        document.body.appendChild(anchor); anchor.click(); setDownloaded(true);
      } finally { anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 10_000); }
    } catch (e) { if (active.current) setError(e instanceof Error ? e.message : String(e)); }
    finally { inFlight.current = false; if (active.current) setDownloading(false); }
  }
  if (!allowed) return null;
  return <section className="panel-card" data-free-csv-export>
    <Button tone="primary" disabled={DEMO || downloading} onClick={() => void download()}>
      {t(downloading ? "csvExport.downloading" : "csvExport.freeDownload")}
    </Button>
    {DEMO && <p>{t("rpt2b2.demoExportsUnavailable")}</p>}
    {error && <p role="alert">{t("csvExport.downloadError", { error })}</p>}
    {downloaded && <p role="status">{t("csvExport.downloaded")}</p>}
  </section>;
}

function NumericalExport({ projectId, runId }: { projectId: string; runId: string }) {
  const { t } = useTranslation();
  const allowed = can("export.csv.basic");
  const [schema, setSchema] = useState<CSVExportSchema | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [downloaded, setDownloaded] = useState(false);
  const [retry, setRetry] = useState(0);
  // S15: the hourly files' formats and the full deliverable (user decision: on by default).
  const [formats, setFormats] = useState<Array<"csv" | "parquet">>(["csv"]);
  const [deliverable, setDeliverable] = useState(true);
  const active = useRef(true);

  useEffect(() => {
    active.current = true;
    return () => { active.current = false; };
  }, []);

  useEffect(() => {
    if (!allowed) return;
    let current = true;
    setLoading(true);
    setError(null);
    setSchema(null);
    exportAPI.exportSchema(projectId, runId).then((value) => {
      if (!current) return;
      setSchema(value);
      setSelected(value.columns.filter((c) => !c.required).map((c) => c.id));
    }).catch((e: unknown) => {
      if (current) setError(e instanceof Error ? e.message : String(e));
    }).finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [projectId, runId, allowed, retry]);

  const download = async () => {
    if (!allowed || downloading || !schema || !selected.length || !formats.length) return;
    setDownloading(true);
    setDownloaded(false);
    setDownloadError(null);
    try {
      const plain = !deliverable && formats.length === 1 && formats[0] === "csv";
      const blob = await exportAPI.exportCSV(projectId, runId, {
        format: "csv", resolution: "hourly", level: "project", columns: selected, ...(plain ? {} : { formats, deliverable })
      });
      if (!active.current) return;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = deliverable ? "RawiBumi_results_bundle.zip" : "RawiBumi_numerical_export.zip";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
      setDownloaded(true);
    } catch (e) {
      if (active.current) setDownloadError(e instanceof Error ? e.message : String(e));
    } finally {
      if (active.current) setDownloading(false);
    }
  };

  if (!allowed) return <div className="empty">{t("csvExport.denied")}</div>;
  if (loading) return <div role="status">{t("csvExport.loading")}</div>;
  if (error) return <div role="alert">{t("csvExport.schemaError", { error })} {DEMO && <p>{t("rpt2b2.demoExportsUnavailable")}</p>} <Button onClick={() => setRetry(retry + 1)}>{t("csvExport.retry")}</Button></div>;
  if (!schema || !schema.row_count || !schema.columns.some((c) => !c.required)) return <div className="empty">{t("csvExport.empty")}</div>;

  return (
    <div className="panel-card" data-csv-export>
      <p>{t("csvExport.scope")}</p>
      <p className="sub">{t("csvExport.rows", { count: schema.row_count })} · {schema.timestamp_convention} · {schema.timezone} · {schema.interval_seconds} s</p>
      <fieldset className="colgroup" disabled={downloading}>
        <legend>{t("csvExport.columns")}</legend>
        {schema.columns.map((c) => (
          <Check key={c.id} disabled={c.required} checked={c.required || selected.includes(c.id)}
            onChange={(on) => {
              setSelected(on ? [...selected, c.id] : selected.filter((id) => id !== c.id));
              setDownloaded(false);
            }}
            label={<>{t(`csvExport.fields.${c.id}`, { defaultValue: c.label })} <span className="sub">({c.unit}){c.required ? ` · ${t("csvExport.required")}` : ""}</span></>} />
        ))}
      </fieldset>
      <fieldset className="colgroup" disabled={downloading} data-export-formats>
        <legend>{t("csvExport.formats")}</legend>
        {(["csv", "parquet"] as const).map((f) => (
          <Check key={f} checked={formats.includes(f)} label={t(`csvExport.${f}`)}
            onChange={(on) => { setFormats(on ? [...formats.filter((x) => x !== f), f].sort() as Array<"csv" | "parquet"> : formats.filter((x) => x !== f)); setDownloaded(false); }} />
        ))}
        {!formats.length && <p className="sub" role="status">{t("csvExport.pickFormat")}</p>}
      </fieldset>
      <Check checked={deliverable} onChange={(on) => { setDeliverable(on); setDownloaded(false); }} label={<>{t("csvExport.deliverable")} <span className="sub">{t("csvExport.deliverableNote")}</span></>} />
      <Button tone="primary" disabled={downloading || !selected.length || !formats.length} onClick={() => void download()}>
        {t(downloading ? "csvExport.downloading" : "csvExport.download")}
      </Button>
      {downloadError && <div role="alert">{t("csvExport.downloadError", { error: downloadError })}</div>}
      {downloaded && <p role="status">{t("csvExport.downloaded")}</p>}
    </div>
  );
}

function NativePDFExport({ projectId, runId, locale }: { projectId: string; runId: string; locale: "en" | "id" }) {
  const { t } = useTranslation();
  const { state } = useStore();
  const allowed = can("export.report.protected_pdf"); // Hint only; the server is authoritative.
  const [enabled, setEnabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const [capabilityError, setCapabilityError] = useState(false);
  const [retry, setRetry] = useState(0);
  const [downloading, setDownloading] = useState(false);
  const [downloaded, setDownloaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const active = useRef(true);
  const inFlight = useRef(false);

  useEffect(() => {
    active.current = true;
    return () => { active.current = false; };
  }, []);

  useEffect(() => {
    if (!allowed) return;
    let current = true;
    setLoading(true);
    setEnabled(false);
    setCapabilityError(false);
    exportAPI.nativePDFCapability().then((value) => {
      if (current) setEnabled(value.enabled);
    }).catch(() => {
      if (current) setCapabilityError(true);
    }).finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [allowed, retry]);

  const download = async () => {
    if (!can("export.report.protected_pdf") || !enabled || loading || inFlight.current) return;
    inFlight.current = true;
    setDownloading(true);
    setDownloaded(false);
    setError(null);
    try {
      const overlay = state.view ? await figureOverlayLoaded(state.view) : null;
      const figure = state.view ? captureReportPlan({ view: state.view, entities: state.entities, modules: state.modules, t, overlay }) : null;
      const blob = await exportAPI.nativePDF(projectId, runId, locale, figure?.png ?? null);
      if (!active.current) return;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      try {
        anchor.href = url;
        anchor.download = "RawiBumi_verified_report.pdf";
        document.body.appendChild(anchor);
        anchor.click();
        setDownloaded(true);
      } finally {
        anchor.remove();
        setTimeout(() => URL.revokeObjectURL(url), 10_000);
      }
    } catch (e) {
      if (active.current) setError(e instanceof Error ? e.message : String(e));
    } finally {
      inFlight.current = false;
      if (active.current) setDownloading(false);
    }
  };

  return <section className="panel-card" data-native-pdf-export aria-busy={allowed && (loading || downloading)}>
    <h3>{t("nativePDF.title")}</h3>
    <p>{t("nativePDF.scope")}</p>
    {!allowed ? <p>{t("nativePDF.denied")}</p>
      : loading ? <p role="status">{t("nativePDF.loading")}</p>
      : !enabled ? <>
        <p role="status">{t(capabilityError ? "nativePDF.capabilityError" : "nativePDF.unavailable")}</p>
        {DEMO && capabilityError && <p>{t("rpt2b2.demoExportsUnavailable")}</p>}
        <Button onClick={() => setRetry(retry + 1)}>{t("nativePDF.retryCapability")}</Button>
      </> : <>
        <Button tone="primary" disabled={downloading} onClick={() => void download()}>
          {t(downloading ? "nativePDF.downloading" : error ? "nativePDF.retryDownload" : "nativePDF.download")}
        </Button>
        {error && <p role="alert">{t("nativePDF.downloadError", { error })}</p>}
        {downloaded && <p role="status">{t("nativePDF.downloaded")}</p>}
      </>}
  </section>;
}

/** DATA1: the whole project as one file, with or without its saved results. */
function ProjectFileSection({ projectId, name }: { projectId: string; name: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  if (DEMO) return null;
  return <section className="panel-card" aria-label={t("data1.projectFile")} data-project-file>
    <div className="panel-card__title">{t("data1.projectFile")}</div>
    <p className="note">{t("data1.projectFileNote")}</p>
    <Button onClick={() => setOpen(true)}>{t("data1.export")}</Button>
    {open && <ExportProjectDialog projectId={projectId} name={name} onClose={() => setOpen(false)} />}
  </section>;
}

export function ExportView() {
  const { t, i18n } = useTranslation();
  const { state } = useStore();
  const view = state.view!;
  const runs = view.bundle.simulation_runs.filter((r) => ["completed", "completed_with_warnings"].includes(r.status));
  const [chosen, setChosen] = useState("");
  const runId = runs.some((r) => r.simulation_run_id === chosen) ? chosen : runs[runs.length - 1]?.simulation_run_id;
  const projectId = view.bundle.project.project_id;
  const locale = i18n.resolvedLanguage === "id" ? "id" : "en";
  return (
    <div className="results">
      <header className="results__head"><div><h2>{t("steps.export")}</h2><div className="sub">{t("csvExport.note")}</div></div></header>
      <ReportPanelWithPxx />
      <ProjectFileSection projectId={projectId} name={view.bundle.project.name} />
      {!runId ? <div className="empty">{t("csvExport.noRun")}</div> : <>
        <Field label={t("csvExport.run")}>
          <Select value={runId} onChange={setChosen} options={runs.map((r) => ({ value: r.simulation_run_id, label: r.simulation_run_id }))} />
        </Field>
        <FreeCSVExport key={`free/${projectId}/${runId}`} projectId={projectId} runId={runId} />
        <NumericalExport key={`${projectId}/${runId}`} projectId={projectId} runId={runId} />
        <NativePDFExport key={`${projectId}/${runId}/${locale}`} projectId={projectId} runId={runId} locale={locale} />
      </>}
    </div>
  );
}
