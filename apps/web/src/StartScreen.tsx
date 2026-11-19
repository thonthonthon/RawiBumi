import i18n from "./i18n";
import { FormEvent, Fragment, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { DEMO, engine } from "./client";
import { MapWorkspace, validMapCoordinates } from "./MapWorkspace";
import { ErrorBoundary } from "./ui/ErrorBoundary";
import { ModalDialog } from "./ui/ModalDialog";
import { track } from "./platform/telemetry";
import { Brand } from "./shell/Brand";
import type { Catalog, ProjectSummary, ProjectSystemSummary, ProjectView, WorkspaceMode } from "./types";
import { Button, Field, NumberInput, Select } from "./ui/kit";
import { ProviderDialogHost } from "./imagery/ProviderDialog";
import { BackupsDialog, ExportProjectDialog, ImportProjectButton } from "./project/ProjectFiles";

export function StartScreen({ projects, catalog, onOpen, onCreated, onImported, onRename, onDelete, busy, loading, unavailable }: { projects: ProjectSummary[]; catalog: Catalog | null; onOpen: (id: string) => void; onCreated: (v: ProjectView) => void; onImported: (v: ProjectView) => void; onRename: (id: string, name: string) => Promise<boolean>; onDelete: (id: string) => Promise<boolean>; busy: boolean; loading: boolean; unavailable: boolean }) {
  const { t } = useTranslation();
  // USE3b: which project rows show their system summary.
  const [open, setOpen] = useState<Record<string, boolean>>({});
  // Summaries are fetched when a row first expands, so the list itself stays as cheap as before.
  const [summaries, setSummaries] = useState<Record<string, ProjectSystemSummary | "loading" | "failed">>({});
  const toggle = (id: string) => {
    const next = !open[id];
    setOpen({ ...open, [id]: next });
    if (!next || (summaries[id] && summaries[id] !== "failed")) return;
    setSummaries((s) => ({ ...s, [id]: "loading" }));
    engine.projectSummary(id).then((summary) => setSummaries((s) => ({ ...s, [id]: summary })))
      .catch(() => setSummaries((s) => ({ ...s, [id]: "failed" })));
  };
  const [name, setName] = useState(() => t("start.defaultName"));
  const [lat, setLat] = useState(-6.2);
  const [lon, setLon] = useState(106.82);
  const [elev, setElev] = useState(0);
  const [tz, setTz] = useState(Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC");
  const [mode, setMode] = useState<WorkspaceMode>("blank_engineering_plane");
  const [action, setAction] = useState<{ kind: "rename" | "delete"; project: ProjectSummary } | null>(null);
  const [actionText, setActionText] = useState("");
  const [files, setFiles] = useState<{ kind: "export" | "backups"; project: ProjectSummary } | null>(null);
  const lastCentre = useRef({ latitude_deg: -6.2, longitude_deg: 106.82 });
  if (validMapCoordinates(lat, lon)) lastCentre.current = { latitude_deg: lat, longitude_deg: lon };
  const latitudeError = !Number.isFinite(lat) || Math.abs(lat) >= 90;
  const longitudeError = !Number.isFinite(lon) || Math.abs(lon) > 180;
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef(false);
  const errorRef = useRef<HTMLParagraphElement>(null);
  useEffect(() => { if (error) errorRef.current?.focus(); }, [error]);
  const empty = useMemo(() => ({ type: "FeatureCollection", features: [] }) as never, []);
  // UX1: the site picker can grow to most of the viewport; "Zoom to point" flies to the typed or picked point.
  const [mapExpanded, setMapExpanded] = useState(false);
  const [zoomRequest, setZoomRequest] = useState(0);
  const siteMap = (
    <MapWorkspace
      compact
      basemaps
      zoomRequest={zoomRequest || undefined}
      site={{ ...lastCentre.current, elevation_m: null, timezone: tz, north_reference: "geodetic_true_north" }}
      geojson={empty}
      onCoordinatePick={(a, b) => {
        setLat(Number(a.toFixed(6)));
        setLon(Number(b.toFixed(6)));
      }}
    />
  );

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy || inFlight.current || latitudeError || longitudeError) return;
    inFlight.current = true; setCreating(true); setError(null);
    try {
      const view = await engine.createProject({ name, latitude_deg: lat, longitude_deg: lon, elevation_m: elev, timezone: tz, workspace_mode: mode });
      track("project.created", { mode });
      onCreated(view);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      inFlight.current = false; setCreating(false);
    }
  }

  return (
    <div className="start">
      <header className="topbar">
        <Brand withBy />
        <span className="topbar__spacer" />
        <a className="btn btn--sm btn--quiet" href={i18n.language === "id" ? "/manual/id.html" : "/manual/index.html"} target="_blank" rel="noopener">{t("header.manual")}</a>
        <span className="topbar__meta">
          {catalog ? t("start.library", { modules: catalog.modules.length, inverters: catalog.inverters.length }) : t(unavailable ? "hardening.libraryUnavailable" : "start.loadingLibrary")}
        </span>
        {DEMO && (
          <span className="demo-flag" title={t("app.demoEngineTitle")}>
            {t("app.demoEngine")}
          </span>
        )}
      </header>

      <main className="start__body" id="main-content" tabIndex={-1}>
        <section className="start__projects" aria-labelledby="projects-title">
          <div className="start__head">
            <h1 id="projects-title">{t("start.projects")}</h1>
            <span className="sub">{t("start.projectsCount", { count: projects.length })}</span>
            {!DEMO && <ImportProjectButton disabled={busy || creating} onImported={onImported} />}
          </div>
          {loading && !projects.length ? <p role="status">{t("hardening.loadingProjects")}</p> : projects.length === 0 ? (
            <p className="empty">{t(unavailable ? "hardening.projectsUnavailable" : "start.noProjects")}</p>
          ) : (
            <table className="tbl tbl--projects">
              <thead>
                <tr>
                  <th scope="col">{t("start.colName")}</th>
                  <th scope="col" className="num">
                    {t("start.colLocation")}
                  </th>
                  <th scope="col">{t("start.colTimezone")}</th>
                  <th scope="col">{t("s7d.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {projects.map((p) => p.status === "unreadable" || p.latitude_deg === null || p.longitude_deg === null ? (
                  // DATA1: a damaged project file is shown, with its reason, so it can be restored from a backup.
                  <tr key={p.project_id} data-unreadable={p.project_id}>
                    <td><span className="start__row">{p.name}</span> <span className="tag tag--draft">{t("data1.unreadable")}</span></td>
                    <td colSpan={2}><span className="sub">{p.reason ?? t("data1.unreadable")}</span></td>
                    <td><div className="row">
                      <Button small disabled={busy || creating} onClick={() => setFiles({ kind: "backups", project: p })}>{t("data1.restoreFromBackup")}</Button>
                      <Button small disabled={busy || creating} onClick={() => { setAction({ kind: "delete", project: p }); setActionText(""); }}>{t("s7d.delete")}</Button>
                    </div></td>
                  </tr>
                ) : (
                  <Fragment key={p.project_id}>
                  <tr>
                    <td>
                      <button type="button" className="linkbtn linkbtn--disclosure" aria-expanded={!!open[p.project_id]} aria-label={t("use3b.details", { name: p.name })}
                        data-project-details={p.project_id} onClick={() => toggle(p.project_id)}>
                        {open[p.project_id] ? "▾" : "▸"}
                      </button>{" "}
                      <button type="button" className="linkbtn start__row" disabled={busy || creating} onClick={() => onOpen(p.project_id)}>
                        {p.name}
                      </button>
                    </td>
                    <td className="num">
                      {p.latitude_deg.toFixed(5)}, {p.longitude_deg.toFixed(5)}
                    </td>
                    <td>{p.timezone}</td>
                    <td><div className="row">{(["rename", "delete"] as const).map((kind) => <Button small key={kind} disabled={busy || creating} onClick={() => {
                      setAction({ kind, project: p }); setActionText(kind === "rename" ? p.name : "");
                    }}>{t(`s7d.${kind}`)}</Button>)}
                      {!DEMO && <Button small disabled={busy || creating} onClick={() => setFiles({ kind: "export", project: p })}>{t("data1.export")}</Button>}
                      {!DEMO && <Button small disabled={busy || creating} onClick={() => setFiles({ kind: "backups", project: p })}>{t("data1.backups")}</Button>}
                    </div></td>
                  </tr>
                  {open[p.project_id] && (
                    <tr className="start__details" data-project-summary={p.project_id}>
                      <td colSpan={4}>{summaries[p.project_id] === "loading" || !summaries[p.project_id] ? <span className="sub">{t("use3b.loading")}</span>
                        : summaries[p.project_id] === "failed" ? <span className="sub">{t("use3b.summaryFailed")}</span>
                        : <SystemSummary system={summaries[p.project_id] as ProjectSystemSummary} />}</td>
                    </tr>
                  )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="start__new" aria-labelledby="new-title">
          <form className="stack" aria-busy={creating} onSubmit={(e) => void submit(e)}>
            <h2 id="new-title">{t("start.newProject")}</h2>
            <Field label={t("start.name")}>
              <input className="input" name="project-name" autoComplete="off" value={name} onChange={(e) => setName(e.target.value)} required />
            </Field>
            <div className="grid2">
              <Field label={t("start.latitude")} unit="°">
                <input className="input input--num" type="number" step="any" value={Number.isNaN(lat) ? "" : lat} aria-invalid={latitudeError} aria-describedby={latitudeError ? "start-latitude-error" : undefined} onChange={(e) => setLat(e.target.value === "" ? NaN : Number(e.target.value))} />
                {latitudeError && <span id="start-latitude-error" role="alert" className="form-error">{t("s7d.latitudeError")}</span>}
              </Field>
              <Field label={t("start.longitude")} unit="°">
                <input className="input input--num" type="number" step="any" value={Number.isNaN(lon) ? "" : lon} aria-invalid={longitudeError} aria-describedby={longitudeError ? "start-longitude-error" : undefined} onChange={(e) => setLon(e.target.value === "" ? NaN : Number(e.target.value))} />
                {longitudeError && <span id="start-longitude-error" role="alert" className="form-error">{t("s7d.longitudeError")}</span>}
              </Field>
              <Field label={t("start.elevation")} unit="m">
                <NumberInput value={elev} step={0.1} onChange={setElev} />
              </Field>
              <Field label={t("start.timezone")}>
                <input className="input" name="timezone" autoComplete="off" spellCheck={false} value={tz} onChange={(e) => setTz(e.target.value)} required />
              </Field>
            </div>
            <Field label={t("start.startIn")}>
              <Select
                value={mode}
                onChange={setMode}
                options={[
                  { value: "blank_engineering_plane", label: t("start.blankPlane") },
                  { value: "map_overlay", label: t("start.mapOverlay") }
                ]}
              />
            </Field>
            <div className="start__map">
              <span className="field__label">{t("start.site")}</span>
              <span className="field__hint">{t("start.siteHint")}</span>
              {!mapExpanded && <ErrorBoundary>{siteMap}</ErrorBoundary>}
              <div className="row">
                <Button small disabled={latitudeError || longitudeError} onClick={() => setZoomRequest((n) => n + 1)}>{t("imagery.zoomToPoint")}</Button>
                <Button small onClick={() => setMapExpanded(true)}>{t("imagery.expandMap")}</Button>
              </div>
            </div>
            {error && <p ref={errorRef} className="form-error" role="alert" tabIndex={-1}>{t("hardening.createFailed", { error })}</p>}
            <Button tone="primary" type="submit" disabled={busy || creating || latitudeError || longitudeError}>
              {t(creating ? "hardening.creating" : "start.create")}
            </Button>
          </form>
        </section>
      </main>
      {mapExpanded && <ModalDialog wide label={t("imagery.expandedTitle")} onClose={() => setMapExpanded(false)}>
        <header className="modal__head"><h2>{t("imagery.expandedTitle")}</h2>
          <span className="sub" data-picked-point>{t("start.latitude")} {Number.isNaN(lat) ? "—" : lat} · {t("start.longitude")} {Number.isNaN(lon) ? "—" : lon}</span></header>
        <div className="modal__body" data-expanded-map>
          <div className="start__map-expanded"><ErrorBoundary>{siteMap}</ErrorBoundary></div>
          <div className="row">
            <Button small disabled={latitudeError || longitudeError} onClick={() => setZoomRequest((n) => n + 1)}>{t("imagery.zoomToPoint")}</Button>
            <Button tone="primary" onClick={() => setMapExpanded(false)}>{t("imagery.useThisPoint")}</Button>
          </div>
        </div>
      </ModalDialog>}
      <ProviderDialogHost />
      {files?.kind === "export" && <ExportProjectDialog projectId={files.project.project_id} name={files.project.name} onClose={() => setFiles(null)} />}
      {files?.kind === "backups" && <BackupsDialog projectId={files.project.project_id} name={files.project.name} onClose={() => setFiles(null)} onRestored={onImported} />}
      {action && <ModalDialog alert={action.kind === "delete"} label={t(`s7d.${action.kind}`)} onClose={() => !busy && setAction(null)}>
        <h2>{t(`s7d.${action.kind}`)}: {action.project.name}</h2>
        {action.kind === "delete" && <p>{t("s7d.deleteWarning")}</p>}
        <Field label={t(action.kind === "delete" ? "s7d.typeName" : "s7d.projectName")}>
          <input className="input" value={actionText} onChange={(e) => setActionText(e.target.value)} maxLength={action.kind === "rename" ? 160 : undefined} />
        </Field>
        <div className="row"><Button cancel disabled={busy} onClick={() => setAction(null)}>{t("s7d.cancel")}</Button>
          <Button tone="primary" disabled={busy || (action.kind === "delete" ? actionText !== action.project.name : !actionText.trim() || actionText.trim().length > 160)} onClick={async () => {
            const success = await (action.kind === "rename" ? onRename(action.project.project_id, actionText.trim()) : onDelete(action.project.project_id));
            if (success) setAction(null);
          }}>{t(`s7d.${action.kind}`)}</Button></div>
      </ModalDialog>}
    </div>
  );
}


/** USE3b: a project's PV, inverters and last successful run, shown when its row expands. */
function SystemSummary({ system }: { system: ProjectSystemSummary }) {
  const { t } = useTranslation();
  const kw = (w: number | null) => (w === null ? "—" : `${(w / 1000).toLocaleString(undefined, { maximumFractionDigits: 2 })} kW`);
  const run = system.last_run;
  return (
    <dl className="start__summary">
      <dt>{t("use3b.pv")}</dt>
      <dd>{system.modules.length ? system.modules.map((m) => `${m.count} × ${m.model} (${m.rating_w === null ? "—" : `${m.rating_w.toFixed(0)} W`})`).join(", ") : t("use3b.none")}
        {system.modules.length > 0 && <> · <strong>{system.dc_kwp.toFixed(2)} kWp</strong></>}</dd>
      <dt>{t("use3b.inverters")}</dt>
      <dd>{system.inverters.length ? system.inverters.map((i) => `${i.count} × ${i.model} (${kw(i.rating_w)})`).join(", ") : t("use3b.none")}
        {system.inverters.length > 0 && <> · <strong>{system.ac_kw.toFixed(1)} kW AC</strong></>}</dd>
      <dt>{t("use3b.lastRun")}</dt>
      <dd>{run ? t("use3b.runLine", {
        energy: run.annual ? `${(run.energy_kwh / 1000).toFixed(2)} MWh/yr` : `${run.energy_kwh.toFixed(1)} kWh`,
        yieldValue: run.specific_yield_kwh_kwp.toFixed(0), pr: run.performance_ratio === null ? "—" : `${(run.performance_ratio * 100).toFixed(1)} %`
      }) : t("use3b.noRun")}</dd>
    </dl>
  );
}
