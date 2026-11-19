/**
 * Frontend capability hints only: these do not authenticate or authorize a
 * requester. Native PDF additionally requires the effective server capability
 * and its Community deployment gate. Hosted access awaits Phase 8 server-side
 * identity/entitlement enforcement; changing this source cannot grant access.
 */
export type Feature =
  | "export.csv.basic"
  | "export.csv.engineering"
  | "export.report.protected_pdf"
  | "export.report.custom_branding"
  | "export.csv"
  | "export.report.native_pdf"
  | "export.report.raster_pdf"
  | "core.design"
  | "core.simulate"
  | "core.export.csv-basic"
  | "core.export.pdf-native"
  | "electrical.sld-full"
  | "export.csv-string-level"
  | "module.finmod"
  /** The HTML report with a customer's name on it (the free report carries no branding). */
  | "report.branded";

type Source = (feature: Feature) => boolean;

const PAID: ReadonlySet<Feature> = new Set(["electrical.sld-full", "export.csv.engineering", "module.finmod", "export.report.custom_branding"]);

/** Self-hosted default: free features on, paid features off. */
const selfHosted: Source = (feature) => !PAID.has(TARGETS[feature] ?? feature);

let source: Source = selfHosted;

const TARGETS: Partial<Record<Feature, Feature>> = {
  "core.export.csv-basic": "export.csv.basic", "export.csv": "export.csv.basic",
  "core.export.pdf-native": "export.report.protected_pdf", "export.report.native_pdf": "export.report.protected_pdf",
  "export.csv-string-level": "export.csv.engineering", "report.branded": "export.report.custom_branding"
};
export function can(feature: Feature): boolean {
  if (feature === "export.report.raster_pdf") return false;
  const target = TARGETS[feature] ?? feature;
  return source(target) && (Object.keys(TARGETS) as Feature[]).every(alias => TARGETS[alias] !== target || source(alias));
}

/** Phase 8: the hosted shell installs a server-backed source after login. */
export function setEntitlementSource(next: Source | null): void {
  source = next ?? selfHosted;
}
