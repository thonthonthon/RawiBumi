import type { useAnnualPxx } from "../results/AnnualPxx";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSiteAddress } from "../site/useSiteAddress";
import { useSystemInfo } from "../site/systemInfo";
import { loadProjectAddress } from "../site/address";
import { loadProjectSystem } from "../site/systemInfo";
import { DEMO, engine } from "../client";
import { demoSeries } from "../demo/series";
import { can } from "../platform/entitlements";
import { buildResultModel, EarlierDesignError, ResultRuleError, runDesignBasis } from "../results/model";
import { useForm, useStore } from "../state/store";
import { Button, Field, FieldGroup, Paid, Segmented, Select } from "../ui/kit";
import { buildReportSnapshot } from "./build";
import { figureOverlay, figureOverlayLoaded } from "../imagery/overlayImage";
import { reportInputFingerprint, type ReportSnapshot, type ReportSnapshotInput, type VerifiedReportSnapshot } from "./snapshot";
import type { ReportTier } from "./template";

/**
 * HTML report (F7, ADR 0016): preview in the page, download as one self-contained HTML file,
 * print to PDF from the browser. Refuses when a blocking S10 result rule fails.
 */
/** UNC1: the report panel with the selected run's annual Pxx fetched from the engine. */
export function ReportPanelWithPxx() {
  const { state } = useStore(), v = state.view!;
  const runs = v.bundle.simulation_runs.filter(r => r.summary_result);
  const [opts] = useForm("report.opts", {runId:runs.at(-1)?.simulation_run_id ?? "",tier:"free" as ReportTier,branding:""});
  const run = runs.find(r => r.simulation_run_id === opts.runId) ?? runs.at(-1);
  const projectId = v.bundle.project.project_id;
  // UXF1 (U2-15): the image overlay is part of the wait, so the plan figure has it once the snapshot arrives.
  const metadata = JSON.stringify([v.bundle.project.site.address,v.bundle.project.site.installation,v.bundle.imagery ?? null]);
  const key = `${projectId}/${run?.simulation_run_id ?? ""}/${v.design_fingerprint}/${metadata}`;
  const [loaded,setLoaded] = useState<{key:string;source:VerifiedReportSnapshot|null;error:string|null}>({key:"",source:null,error:null});
  useEffect(() => {
    if (!run) return;
    const controller = new AbortController();
    void Promise.all([loadProjectAddress(projectId),loadProjectSystem(projectId),figureOverlayLoaded(v)])
      .then(() => engine.reportSnapshot(projectId,run.simulation_run_id,controller.signal))
      .then(source => { if (!controller.signal.aborted) setLoaded({key,source,error:null}); })
      .catch(error => { if (!controller.signal.aborted) setLoaded({key,source:null,error:String(error)}); });
    return () => controller.abort();
  }, [key,projectId,run?.simulation_run_id]);
  const current = loaded.key === key;
  return <ReportPanel verifiedSource={current ? loaded.source : null} snapshotLoading={!current} snapshotError={current ? loaded.error : null} />;
}

/** `pxx` undefined: no Pxx in this report; null: still loading (the panel waits, like the address lookup). */
export function ReportPanel({ pxx, verifiedSource, snapshotLoading = false, snapshotError }: {
  pxx?: ReturnType<typeof useAnnualPxx>; verifiedSource?: VerifiedReportSnapshot | null;
  snapshotLoading?: boolean; snapshotError?: string | null;
} = {}) {
  const { t, i18n } = useTranslation();
  const { state, toast } = useStore();
  const v = state.view!;
  const site = v.bundle.project.site;
  const [system] = useSystemInfo(v.bundle.project.project_id);
  const address = useSiteAddress(v.bundle.project.project_id, site.latitude_deg, site.longitude_deg, i18n.language);
  const runs = v.bundle.simulation_runs.filter((r) => r.summary_result);
  const [opts, setOpts] = useForm("report.opts", { runId: runs[runs.length - 1]?.simulation_run_id ?? "", tier: "free" as ReportTier, branding: "" });
  const [report, setReport] = useForm<ReportSnapshot | null>("report.snapshot", null);
  const [error, setError] = useState<string | null>(null);
  const branded = can("report.branded");
  const runId = runs.some((r) => r.simulation_run_id === opts.runId) ? opts.runId : (runs[runs.length - 1]?.simulation_run_id ?? "");
  const run = runs.find((r) => r.simulation_run_id === runId);
  const basis = snapshotError?.includes("earlier_design") ? "earlier" : verifiedSource
    ? "current" : verifiedSource === undefined && run ? runDesignBasis(v, run) : "unknown";

  const hourly = useMemo(() => {
    if (!DEMO || !run) return null;
    const m = buildResultModel(v, run, { authority: "DEMO_SYNTHETIC", hourlyAcKw: null });
    if (m.dcKwp === null) return null;
    return demoSeries(m.dcKwp, m.acKw || 1).acAfter;
  }, [v, run]);

  const input: ReportSnapshotInput = {
    verifiedSource: verifiedSource ?? undefined,
    view: v,
    entities: state.entities,
    modules: state.modules,
    runId,
    authority: DEMO ? "DEMO_SYNTHETIC" : "ENGINE",
    hourlyAcKw: hourly,
    tier: opts.tier === "branded" && branded ? "branded" : "free",
    branding: opts.branding,
    address: address.address,
    system,
    annualPxx: pxx?.view ?? null,
    language: i18n.language,
    overlay: figureOverlay(v),
    t
  };
  const inputFingerprint = reportInputFingerprint(input);
  const current = report?.inputFingerprint === inputFingerprint ? report : null;
  const stale = report !== null && current === null;
  // UNC1: the run's annual Pxx enters the report (and its input fingerprint); wait for it like the address lookup.
  const addressLooking = snapshotLoading || (!!snapshotError && basis !== "earlier") || (address.status === "looking" || address.status === "saving") || (!!run && pxx === null);

  if (!runs.length) return <div className="empty">{t("report.noRun")}</div>;

  const make = () => {
    if (addressLooking) return null;
    if (current) return current;
    try {
      if (basis === "earlier") throw new EarlierDesignError("earlier");
      const r = buildReportSnapshot(input);
      setReport(r);
      setError(null);
      return r;
    } catch (e) {
      const msg = e instanceof ResultRuleError ? t("report.refused", { rules: e.failures.map((f) => f.id).join(", ") })
        : e instanceof EarlierDesignError ? t(e.basis === "earlier" ? "res1.reportEarlier" : "res1.reportUnknown") : (e as Error).message;
      setError(msg);
      setReport(null);
      toast("error", msg);
      return null;
    }
  };
  const download = () => {
    if (addressLooking) return;
    const r = current ?? make();
    if (!r) return;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([r.html], { type: "text/html" }));
    a.download = `RawiBumi_report_${v.bundle.project.name.replace(/[^\w-]+/g, "_")}_${runId}.html`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 10_000);
  };

  return (
    <div className="panel-card report-panel">
      <div className="panel-card__title">{t("report.panelTitle")}</div>
      <p className="note">{t("report.panelNote")}</p>
      <p className="note" data-report-address>
        {t("report.address")}: {address.address?.text.trim() || (address.status === "looking" ? t("site.looking") : t("report.addressNone"))} · {t("report.addressEditIn")}
      </p>
      <div className="grid2">
        <Field label={t("results.run")}>
          <Select value={runId} onChange={(id) => setOpts({ ...opts, runId: id })} options={runs.map((r) => ({ value: r.simulation_run_id, label: r.simulation_run_id }))} />
        </Field>
        <FieldGroup label={t("report.tier")}>
          <Segmented<ReportTier>
            label={t("report.tier")}
            value={opts.tier}
            onChange={(tier) => setOpts({ ...opts, tier })}
            options={[
              { value: "free", label: t("report.tierFree") },
              { value: "branded", label: t("report.tierBranded"), disabled: !branded, title: branded ? undefined : t("report.brandedPaid") }
            ]}
          />
          {!branded && <Paid what={t("report.tierBranded")} />}
        </FieldGroup>
      </div>
      {opts.tier === "branded" && branded && (
        <Field label={t("report.branding")}>
          <input className="input" value={opts.branding} onChange={(e) => setOpts({ ...opts, branding: e.target.value })} />
        </Field>
      )}
      {snapshotLoading && <p role="status">{t("rpt2b1.loading")}</p>}
      {snapshotError && !snapshotError.includes("earlier_design") && <p role="alert">{t("rpt2b1.error",{error:snapshotError})}</p>}
      {!snapshotLoading && !snapshotError && addressLooking && <p role="status">{t("site.looking")}</p>}
      {basis !== "current" && <p className="issue" role="status" data-report-design-basis={basis}>{t(basis === "earlier" ? "res1.reportEarlier" : "res1.reportUnknown")}</p>}
      <div className="row">
        <Button tone="primary" disabled={addressLooking} title={addressLooking ? t("site.looking") : undefined} onClick={make}>
          {t("report.preview")}
        </Button>
        <Button disabled={addressLooking} title={addressLooking ? t("site.looking") : undefined} onClick={download}>{t("report.download")}</Button>
        {current && <span className="sub">{t("report.fingerprintIs", { fp: current.modelFingerprint })}</span>}
      </div>
      {stale && <p className="note" role="status" aria-live="polite" data-report-stale>{t("report.stalePreview")}</p>}
      {error && (
        <div className="issue issue--blocking" role="alert">
          {error}
        </div>
      )}
      {current && <iframe className="report-frame" title={t("report.frameTitle")} data-report-snapshot-id={current.snapshotId} srcDoc={current.html} sandbox="allow-same-origin" />}
    </div>
  );
}
