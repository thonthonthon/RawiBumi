import { renderPlanFigure } from "../canvas/figure";
import { overlayStringsOf } from "../canvas/plan/electricalOverlay";
import { modulesFromView } from "../state/store";
import { enginePlaneToUi, type Vec2 } from "../geometry";
import { EMPTY_SYSTEM } from "./presentation";
import type { Entity, ModuleShape } from "../state/store";
import { fieldSupportIds } from "../types";
import type { ProjectView, AnnualPxxView } from "../types";
import type { SiteAddress } from "../site/address";
import type { SystemInfo } from "./presentation";
import { createReportSnapshot, reportInputFingerprint, type ReportSnapshot, type ReportSnapshotInput } from "./snapshot";

import { reportModel, type Authority } from "../results/model";
import type { ReportTier } from "./template";
import { renderReportDetails } from "./render";
export { reportCssText, dateInZone } from "./render";
export interface BuildReportInput {
  verifiedSource?: import("./snapshot").VerifiedReportSnapshot;
  view: ProjectView;
  entities: readonly Entity[];
  modules: readonly ModuleShape[];
  runId: string;
  authority: Authority;
  hourlyAcKw: number[][] | null;
  tier: ReportTier;
  branding: string;
  /** Site address from the Site panel (looked up or typed), if any. */
  address: SiteAddress | null;
  /** Installation type and BESS capacity from the Site panel (F7.2). */
  system?: SystemInfo;
  /** UNC1: the engine's annual-Pxx view of the run (the panel fetches it; absent elsewhere). */
  annualPxx?: AnnualPxxView | null;
  /** UXF1 (U2-15): the user's calibrated image overlay under the plan figure, when its image has loaded. */
  overlay?: import("../imagery/overlayImage").FigureOverlay | null;
  t: (key: string, opts?: Record<string, unknown>) => string;
  now?: Date;
}

/** Adapt only server-snapshot design/data to the existing presentation functions. */
function verifiedInput(i: BuildReportInput): BuildReportInput {
  const source = i.verifiedSource;
  if (!source) return i;
  const view = source.design_view, site = source.site;
  const entities: Entity[] = view.scene_view.local_features.filter(f => f.category !== "module").map(f => {
    const surface = view.bundle.scene.surfaces.find(s => s.surface_id === f.id);
    return { id:f.id,kind:f.category === "surface" ? "surface" : "obstacle",subtype:f.subtype,name:f.name,
      polygon:f.polygon.map(p => [p[0],p[1]] as Vec2),holes:(surface?.boundary_2d?.holes ?? []).map(h => h.map(p => [p[0],p[1]] as Vec2)),
      plane:enginePlaneToUi(f.polygon,surface ?? {}),height_m:0,source:"engine",modified:false,pending:[],locked:false,hidden:false,
      hostsPvField:view.bundle.scene.pv_fields.some(field => fieldSupportIds(field).includes(f.id)) };
  });
  const px = source.annual_pxx;
  let annualPxx: AnnualPxxView | null = null;
  if (px.status !== "no_uncertainty_ledger") {
    if (!px.basis || !px.label) throw new Error("Malformed verified snapshot Pxx basis");
    annualPxx = {schema_name:"AnnualPxxView",run_id:source.identity.simulation_run_id,status:px.status === "available" ? "available" : "unavailable",
      reasons:px.reasons ?? [],basis:px.basis,ledger_sha256:px.ledger_sha256 ?? null,result:px.result ?? null,label:px.label,
      P99:{status:"unavailable",reason:px.P99_reason,message:px.P99_message}};
  }
  return {...i,view,runId:source.identity.simulation_run_id,entities,modules:modulesFromView(view),
    hourlyAcKw:source.hourly_ac.values?.map(row => row.map(value => value ?? NaN)) ?? null,address:site.address ?? null,system:{...EMPTY_SYSTEM,...site.installation},annualPxx};
}

// The PDF accepts a plan PNG of at most 4 MiB (reporting/exports/native_pdf.py validate_plan_png).
const MAX_FIGURE_BYTES = 4 * 1024 * 1024;
const pngBytes = (dataUrl: string) => Math.floor((dataUrl.length - dataUrl.indexOf(",") - 1) * 3 / 4);

/** Browser-only illustrative figure; shared by the HTML and PDF download. */
export function captureReportPlan(i: Pick<BuildReportInput, "view" | "entities" | "modules" | "t" | "overlay">): ReturnType<typeof renderPlanFigure> | null {
  const render = (overlay: BuildReportInput["overlay"], dpr: number, note?: string) => renderPlanFigure({
    entities: i.entities,
    modules: i.modules,
    strings: overlayStringsOf(i.view, i.modules),
    electrical: true,
    size: { w: 900, h: 540 },
    dpr,
    overlay,
    labels: { north: i.t("plan.north"), draft: i.t("report.draft"), note }
  });
  try {
    if (!i.overlay) return render(null, 2);
    // A photo background can outgrow the PDF's limit at print resolution. At dpr 1 (900 x 540 RGBA) even an
    // uncompressible PNG stays under 2 MiB, so halving the resolution always fits.
    const figure = render(i.overlay, 2, i.t("report.overlayCaption"));
    return pngBytes(figure.png) <= MAX_FIGURE_BYTES ? figure : render(i.overlay, 1, i.t("report.overlayCaption"));
  } catch {
    return null; // No WebGL: the report says the figure is unavailable.
  }
}

export function buildReport(input: BuildReportInput): { html: string; fingerprint: string } {
  if (!input.verifiedSource) {
    reportModel(input.view, input.runId, { authority: input.authority, hourlyAcKw: input.hourlyAcKw });
    throw new Error("A verified report snapshot is required.");
  }
  const i = verifiedInput(input);
  const planFigure = captureReportPlan(i);
  return renderReportDetails(input.verifiedSource, { locale: i.t("report.lang") === "id" ? "id" : "en", planFigurePng: planFigure?.png ?? null, watermark: "free_community", tier: i.tier, branding: i.branding, authority: i.authority });
}
/** Capture the exact generated HTML and its inputs without changing the model identity. */
export function buildReportSnapshot(i: ReportSnapshotInput): ReportSnapshot {
  const now = i.now ?? new Date();
  return createReportSnapshot(buildReport({ ...i, now }), reportInputFingerprint(i), now.toISOString());
}
