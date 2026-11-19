import type { BuildReportInput } from "./build";
import { EMPTY_SYSTEM } from "./presentation";

/** JSON semantics, with recursively sorted object keys and unchanged array order. */
export function canonicalSerialize(value: unknown): string {
  const encode = (v: unknown): string | undefined => {
    if (v instanceof Date) return encode(v.toJSON());
    if (Array.isArray(v)) return `[${Array.from(v, (item) => encode(item) ?? "null").join(",")}]`;
    if (v !== null && typeof v === "object") {
      const object = v as Record<string, unknown>;
      const fields = Object.keys(object).sort().flatMap((key) => {
        const encoded = encode(object[key]);
        return encoded === undefined ? [] : [`${JSON.stringify(key)}:${encoded}`];
      });
      return `{${fields.join(",")}}`;
    }
    return JSON.stringify(v);
  };
  const encoded = encode(value);
  if (encoded === undefined) throw new TypeError("Report input must be JSON serializable.");
  return encoded;
}

/** Deterministic cache identity, independent of the engineering-model fingerprint. */
function fingerprint(text: string): string {
  let a = 0x811c9dc5;
  let b = 0x9e3779b9;
  for (let n = 0; n < text.length; n++) {
    const code = text.charCodeAt(n);
    a = Math.imul(a ^ code, 0x01000193) >>> 0;
    b = Math.imul(b ^ code, 0x01000193) >>> 0;
  }
  return a.toString(16).padStart(8, "0") + b.toString(16).padStart(8, "0");
}

export type ReportSnapshotInput = BuildReportInput & { language: string };

/** Values actually used by the template; address lookup metadata does not affect HTML. */
export function effectiveReportOptions(i: Pick<BuildReportInput, "tier" | "branding" | "address" | "system">) {
  const address = i.address?.text.trim() || null;
  return {
    tier: i.tier,
    branding: i.tier === "branded" ? i.branding.trim() : "",
    address,
    addressAttribution: address ? (i.address?.attribution || null) : null,
    system: i.system ?? EMPTY_SYSTEM
  };
}

/** All report data, including the selected run's contents; no generation/lookup clock. */
export function reportInputFingerprint(i: ReportSnapshotInput): string {
  if (i.verifiedSource) return fingerprint(canonicalSerialize({snapshot:i.verifiedSource.snapshot_sha256,
    tier:i.tier,branding:i.tier === "branded" ? i.branding.trim() : "",language:i.language}));
  const { bundle, catalog, topology_view, topology_checks } = i.view;
  return fingerprint(canonicalSerialize({
    project: bundle.project,
    scene: bundle.scene,
    electricalDesign: bundle.electrical_design,
    catalog,
    topologyView: topology_view,
    topologyChecks: topology_checks,
    entities: i.entities,
    modules: i.modules,
    runId: i.runId,
    run: bundle.simulation_runs.find((run) => run.simulation_run_id === i.runId) ?? null,
    authority: i.authority,
    hourlyAcKw: i.hourlyAcKw,
    annualPxx: i.annualPxx ?? null,
    ...effectiveReportOptions(i),
    language: i.language
  }));
}

export interface ReportSnapshot {
  readonly html: string;
  readonly modelFingerprint: string;
  readonly inputFingerprint: string;
  readonly snapshotId: string;
  readonly generatedAt: string;
}

/** Strings only: a shallow freeze also makes the entire snapshot immutable. */
export function createReportSnapshot(
  report: { html: string; fingerprint: string },
  inputFingerprint: string,
  generatedAt: string
): ReportSnapshot {
  return Object.freeze({
    html: report.html,
    modelFingerprint: report.fingerprint,
    inputFingerprint,
    snapshotId: fingerprint(canonicalSerialize({ inputFingerprint, html: report.html })),
    generatedAt
  });
}


/** Scientific data from the verified run boundary, independent of rendered HTML. */
export interface VerifiedReportSnapshot {
  schema: "rawibumi.report_snapshot.v1";
  snapshot_sha256: string;
  design_view: import("../types").ProjectView;
  summary: import("../types").SummaryResult;
  identity: { project_id: string; simulation_run_id: string; package_manifest_sha256: string; name: string };
  site: import("../types").ProjectView["bundle"]["project"]["site"];
  monthly: { dc_kwp: number | null; monthly: Array<Record<string,unknown>>; period: { pr: number | null } };
  hourly_ac: { interval_seconds: number; values: Array<Array<number | null>> | null; days?: string[]; timestamps?: string[]; power_kw?: number[] };
  annual_pxx: { status: string; P99: null; P99_reason: string; P99_message: string;
    result?: import("../types").AnnualPxxView["result"]; reasons?: import("../types").AnnualPxxView["reasons"];
    basis?: import("../types").AnnualPxxView["basis"]; ledger_sha256?: string | null; label?: import("../types").AnnualPxxView["label"] };
  method: {
    limits: Array<{code:string;en:string;id:string;applies?:boolean}>;
    recorded_assumptions: unknown[];
    loss_disclosures: Array<{code:string;label:string;fraction:number|null;not_included:boolean;
      suggestions?:Array<{module_revision_id?:string;fraction:number|null;applied:false;reason:string|null}>}>;
    stc_notices: Array<{module_revision_id:string;nameplate_w:number;model_stc_w:number;deviation_fraction:number;basis:string}>;
  };
  provenance: {free_csv_schema: string; source_package_manifest_sha256?: string; source_timezone?: string; source_interval?: Record<string, unknown>; source_dataset?: {sha256?: string}; source_identities?: Record<string, unknown>};
  checks: Record<string,unknown>;
}
