import type { AnnualPxxView } from "../types";
import { isAnnualResult, isCompleteYearResult, type ResultModel, type RuleResult } from "../results/model";
import { beyondSimulation, formatEnergy, formatPower, formatPvCapacity, type SystemInfo } from "./presentation";

/**
 * The HTML report template (F7, ADR 0016; revised in F7.1). A pure function: the same inputs give
 * the same document. Every text that comes from the project or the user is escaped (S10 a17). The
 * free tier carries no customer branding (S10 a18); synthetic data is stamped (S10 a01).
 *
 * F7.1, as directed by the owner: a cover with the project identity (name, address, coordinates,
 * no engineering revision data), a linked table of contents (no page numbers until the server
 * PDF), one mapping table per inverter with azimuth and tilt, and a sun-path and shading chapter.
 * The run ID and fingerprint appear once, in the Methodology chapter.
 */

export type ReportTier = "free" | "branded";

export interface ReportInput {
  imported?: boolean;
  periodAware?: boolean;
  model: ResultModel;
  rules: RuleResult[];
  tier: ReportTier;
  /** Customer or company name for the branded tier; ignored on the free tier. */
  branding: string;
  /** Plan figure from the workstation renderer, a PNG data URL. */
  planFigure: { png: string; width: number; height: number } | null;
  /** SLD drawing from the workstation component, SVG markup. */
  sldSvg: string;
  charts: { monthly: string; waterfall: string | null; heatmap: string | null; data?: Record<string, unknown> };
  fingerprint: string;
  generatedAt: string;
  /** Project identity for the cover. */
  identity: ReportIdentity;
  /** Inline CSS: the shared tokens, the report sheet and the embedded fonts. */
  css: string;
  /** Lettering, from i18n. */
  t: (key: string, opts?: Record<string, unknown>) => string;
  /** UNC1: the engine's annual-Pxx view of this run (absent in callers that don't fetch it). */
  annualPxx?: AnnualPxxView | null;
  verifiedSource?: import("./snapshot").VerifiedReportSnapshot;
}

export interface ReportIdentity {
  /** Null when no address was looked up or typed. */
  address: string | null;
  /** Credit line of the lookup service the address came from, if any. */
  addressAttribution: string | null;
  latitude: number;
  longitude: number;
  elevationM: number | null;
  /** Date of issue, YYYY-MM-DD, in the site's timezone. */
  issuedOn: string;
  /** Installation type and BESS capacity as entered by the user (F7.2). */
  system: SystemInfo;
}

export function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

const n0 = (x: number) => x.toLocaleString("en-US", { maximumFractionDigits: 0 });
const n1 = (x: number) => x.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

const deg = (x: number) => `${x.toLocaleString("en-US", { maximumFractionDigits: 1 })}°`;

/** Latitude and longitude with hemisphere, 5 decimals (about 1 m). */
export function formatCoordinates(lat: number, lon: number): string {
  const f = (x: number) => Math.abs(x).toFixed(5);
  return `${f(lat)}° ${lat < 0 ? "S" : "N"}, ${f(lon)}° ${lon < 0 ? "W" : "E"}`;
}

/** The report's chapters, in order (S10 a21: chapter coverage; F7.1 order). */
export const CHAPTERS = ["kpis", "plan", "topology", "sld", "shading", "monthly", "losses", "heatmap", "checks", "method", "assumptions", "scope"] as const;

export function renderReportHtml(r: ReportInput): string {
  const { model: m, t } = r;
  if (!r.periodAware && !isAnnualResult(m)) throw new Error("Annual report requires finite, nonnegative annual energy, exactly 8,760 period hours and 12 monthly bins.");
  const annual = r.periodAware ? isCompleteYearResult(m) : isAnnualResult(m);
  const energy = annual ? m.annualAcKwh! : m.periodAcKwh;
  const na = t("rpt2b2.partialNotApplicable");
  const e = escapeHtml;
  const synthetic = m.authority === "DEMO_SYNTHETIC";
  const months = annual ? t("results.monthsShort").split(",") : r.verifiedSource!.summary.monthly_energy.map(row => row.month);
  const chapter = (id: (typeof CHAPTERS)[number], body: string) => {
    const i = CHAPTERS.indexOf(id) + 1;
    return `<section id="ch-${id}" data-chapter="${id}"><h2><span class="num">${i}</span>${e(t(`report.ch_${id}`))}</h2>${body}</section>`;
  };
  const stamp = synthetic ? `<p><span class="stamp">${e(t("report.syntheticStamp"))}</span></p>` : "";
  const client = r.tier === "branded" ? r.branding.trim() : "";
  const id = r.identity;
  const notGiven = `<span class="muted">${e(t("report.addressNone"))}</span>`;
  const b = id.system;
  const bess =
    b.bessEnergyKwh === null
      ? notGiven
      : b.bessEnergyKwh === 0 && !b.bessPowerKw
        ? e(t("report.bessNone"))
        : e([b.bessPowerKw ? formatPower(b.bessPowerKw) : null, formatEnergy(b.bessEnergyKwh)].filter(Boolean).join(" / "));
  const systemNote = beyondSimulation(b) ? `<p class="note-warn" data-not-simulated>${e(t("report.systemNotSimulated"))}</p>` : "";

  // Cover: project identity only; no run, revision or fingerprint data (owner's direction, F7.1).
  const row = (k: string, v: string, attrs = "") => `<tr${attrs}><th>${e(k)}</th><td>${v}</td></tr>`;
  const cover = `<section class="cover" data-cover>
    <div class="rep-brand">RawiBumi</div>
    <h1>${e(m.project)}</h1>
    <div class="rep-sub">${e(t("report.title"))}</div>
    ${stamp}
    ${r.imported ? `<p data-imported-run>${e(t("r1.importedRun"))}</p>` : ""}
    <table class="identity"><tbody>
      ${client ? row(t("report.client"), e(client), " data-branding") : ""}
      ${row(t("report.project"), e(m.project))}
      ${row(t("report.installationType"), id.system.installationType ? e(t(`site.type_${id.system.installationType}`)) : notGiven, " data-installation-type")}
      ${row(t("report.pvCapacity"), e(m.dcKwp === null ? "—" : formatPvCapacity(m.dcKwp)), " data-pv-capacity")}
      ${row(t("report.bessCapacity"), bess, " data-bess")}
      ${row(t("report.address"), id.address?.trim() ? e(id.address.trim()) : `<span class="muted">${e(t("report.addressNone"))}</span>`, ` data-address`)}
      ${row(t("report.coordinates"), e(formatCoordinates(id.latitude, id.longitude)))}
      ${id.elevationM !== null ? row(t("report.elevation"), `${n0(id.elevationM)} m`) : ""}
      ${row(t("report.timezone"), e(m.timezone))}
      ${row(t("report.issued"), e(id.issuedOn))}
    </tbody></table>
    ${systemNote}
    ${id.address?.trim() && id.addressAttribution ? `<p class="muted small">${e(t("report.addressCredit", { attribution: id.addressAttribution }))}</p>` : ""}
    <nav class="toc" aria-labelledby="toc-h" data-toc><h2 id="toc-h">${e(t("report.contents"))}</h2><ol>${CHAPTERS.map(
      (c, i) => `<li><a href="#ch-${c}"><span class="num">${i + 1}</span>${e(t(`report.ch_${c}`))}</a></li>`
    ).join("")}</ol></nav>
  </section>`;

  const source = r.verifiedSource;
  const lang = t("report.lang") === "id" ? "id" : "en";
  const additions = !source ? "" : `<div data-report-snapshot-additions>
    <h3>${e(t("rpt2b1.method"))}</h3>
    <ul data-report-method-limits>${source.method.limits.filter(limit => limit.applies !== false).map(limit => `<li data-limit-code="${e(limit.code)}">${e(limit[lang])}</li>`).join("")}</ul>
    <table data-report-loss-disclosures><tbody>${source.method.loss_disclosures.map(loss => `<tr><th>${e(t(`rpt2b1.${loss.code}`,{defaultValue:loss.label}))}</th><td>${loss.fraction === null ? e(t("rpt2b1.unavailable")) : loss.not_included ? e(t("rpt2b1.zeroNotIncluded")) : `${n1(loss.fraction*100)} %`}</td><td>${(loss.suggestions??[]).map(item => item.fraction === null ? e(t("rpt2b1.panUnavailable")) : e(t("rpt2b1.panSuggestion",{value:n1(item.fraction*100)}))).join("; ")}</td></tr>`).join("")}</tbody></table>
    ${source.method.stc_notices.map(notice => `<p data-stc-module="${e(notice.module_revision_id)}">${e(t("rpt2b1.stcNotice",{deviation:n1(notice.deviation_fraction*100),model:n1(notice.model_stc_w),nameplate:n1(notice.nameplate_w)}))} ${e(notice.basis)}</p>`).join("")}
    <p data-report-p99-reason="${e(annual ? source.annual_pxx.P99_reason : "partial_period")}">P99: ${e(annual ? t(source.annual_pxx.P99_reason === "no_uncertainty_ledger" ? "rpt2b1.noLedger" : "unc1.p99") : na)} (${e(annual ? source.annual_pxx.P99_reason : "partial_period")})</p>
    <table data-report-provenance><tbody>${[
      [t("rpt2b2.projectId"),source.identity.project_id],
      [t("rpt2b2.weatherRevision"),source.provenance.source_identities?.weather_revision_id],
      [t("rpt2b2.sourceTimezone"),source.provenance.source_timezone],
      [t("rpt2b2.intervalSeconds"),source.provenance.source_interval?.interval_seconds],
      [t("rpt2b2.timestampConvention"),source.provenance.source_interval?.source_timestamp_convention],
      [t("rpt2b2.engineVersion"),source.provenance.source_identities?.engine_version],
      [t("rpt2b2.inputHash"),source.provenance.source_identities?.input_hash],
      [t("rpt2b2.datasetHash"),source.provenance.source_dataset?.sha256]
    ].map(([label,value]) => `<tr><th>${e(String(label))}</th><td>${e(value === null || value === undefined ? t("rpt2b1.unavailable") : String(value))}</td></tr>`).join("")}</tbody></table>
    <p data-export-manifest>${e(t("rpt2b2.exportManifest"))}: export-manifest.json · ${e(source.provenance.free_csv_schema)}</p>
    <p>${e(t("rpt2b1.packageHash"))}: <code>${e(source.identity.package_manifest_sha256)}</code></p>
    <p>${e(t("rpt2b1.snapshot"))}: <code>${e(source.snapshot_sha256)}</code></p>
    </div><!-- snapshot-additions-end -->`;
  const methodBody = `
    <table><tbody>
      <tr><th>${e(t("report.run"))}</th><td><code>${e(m.runId)}</code></td></tr>
      <tr><th>${e(t("report.period"))}</th><td>${e((r.periodAware ? m.periodStart : m.periodStart.slice(0, 10)))} → ${e((r.periodAware ? m.periodEnd : m.periodEnd.slice(0, 10)))} (${n0(m.periodHours)} h, ${e(m.timezone)})</td></tr>
      <tr><th>${e(t("report.authority"))}</th><td>${e(t(synthetic ? "report.authoritySynthetic" : "report.authorityEngine"))}</td></tr>
      <tr><th>${e(t("report.fingerprint"))}</th><td><code>${e(r.fingerprint)}</code></td></tr>
      <tr><th>${e(t("report.generated"))}</th><td>${e(r.generatedAt)}</td></tr>
    </tbody></table>${additions}`;

  // UNC1: annual P50–P95 (model-based, assumption-based) or why it's unavailable; P99 is never shown as a number.
  const px = r.annualPxx;
  const pxxBody = !annual ? `<p data-report-pxx="not-applicable">${e(na)}</p>` : !px ? "" : px.result
    ? `<h3>${e(t("unc1.reportTitle"))}</h3><table data-report-pxx><tbody>${(["P50", "P75", "P90", "P95"] as const)
        .map((k) => `<tr><th>${k}</th><td>${(px.result!.quantiles[k].energy_kwh / 1000).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} MWh</td><td class="muted">${e(t("unc1.exceeded", { p: Number(k.slice(1)) }))}</td></tr>`).join("")}
        <tr><th>P99</th><td>—</td><td class="muted">${e(t("unc1.p99"))}</td></tr></tbody></table>
      <p class="muted">${e(t(`unc1.basis_${px.basis.annual_mean_basis}`))} ${e(t("unc1.label"))}</p>`
    : `<h3>${e(t("unc1.reportTitle"))}</h3><p class="muted" data-report-pxx="unavailable">${e(t("unc1.reportUnavailable", { reasons: px.reasons.map((x) => t(`unc1.reason_${x.code}`, { defaultValue: x.message })).join(" ") }))}</p>`;
  const kpi = (label: string, value: string, unit: string, attrs = "") => `<div${attrs}><span>${e(label)}</span><strong>${value}</strong><em>${e(unit)}</em></div>`;
  const kpisBody = `${annual ? "" : `<p data-period-scope>${e(t("rpt2b2.simulatedPeriod"))}</p>`}<div class="kpis">
      ${kpi(t("results.referenceProduction"), n1(annual ? energy / 1000 : energy), annual ? "MWh" : "kWh")}
      ${annual ? kpi(t("results.kpiYield"), n0(m.specificYield), "kWh/kWp") : kpi(t("results.kpiYield"), e(na), "")}
      ${source?.monthly.period.pr === null
        ? kpi(t("results.kpiPr"), "—", t("rpt2b2.noPoaReference"), ' data-report-pr-reason="no_poa_reference"')
        : kpi(t("results.kpiPr"), n1(m.performanceRatio * 100), "%")}
      ${kpi(t("report.dcCapacity"), m.dcKwp === null ? "—" : n1(m.dcKwp), "kWp")}
      ${kpi(t("report.acCapacity"), m.acKw === null ? "—" : n1(m.acKw), "kW")}
      ${kpi(t("results.kpiClipping"), n1(m.clippingKwh / 1000), "MWh")}
    </div><p class="muted">${e(t("report.prBasis"))}</p>${pxxBody}`;

  const planBody = r.planFigure
    ? `<figure><img src="${r.planFigure.png}" width="${r.planFigure.width}" height="${r.planFigure.height}" alt="${e(t("report.planAlt"))}" data-plan-figure style="max-height:160mm;object-fit:contain;"><figcaption>${e(t("report.planCaption"))} ${source ? e(t("rpt2b2.illustrative")) : ""}</figcaption></figure>`
    : `<p class="muted">${e(t(r.periodAware ? "rpt2b2.planAbsent" : "report.planUnavailable"))}</p>`;

  const orient = (o: string) => (o === "portrait" || o === "landscape" ? t(`report.orient_${o}`) : o);
  const anyMixed = m.inverters.some((b) => b.rows.some((x) => x.mixed));
  const invTable = (b: (typeof m.inverters)[number]) => {
    const ratio = b.acKw > 0 && b.dcKwp > 0 ? (b.dcKwp / b.acKw).toFixed(2) : "–";
    const head = `<h3>${e(b.name)} · ${e(b.model)}</h3>
      <p class="inv-meta"><span>${e(t("report.acRating"))} <strong>${n1(b.acKw)} kW</strong></span><span>${e(t("report.dcCapacity"))} <strong>${n1(b.dcKwp)} kWp</strong></span><span>${e(t("report.dcAcRatio"))} <strong>${ratio}</strong></span>${
        b.moduleModels.length ? `<span>${e(t("report.moduleType"))} <strong>${e(b.moduleModels.join("; "))}</strong></span>` : ""
      }</p>`;
    if (!b.rows.length) return `<div class="inv" data-inverter="${e(b.name)}">${head}<p class="muted">${e(t("report.noStrings"))}</p></div>`;
    const cells = (x: (typeof b.rows)[number]) => {
      if (!x.fields.length) return `<td>–</td><td class="num">–</td><td class="num">–</td><td>–</td>`;
      if (!x.mixed) {
        const f = x.fields[0];
        const placements = [...new Set(x.fields.map((g) => orient(g.moduleOrientation)))].join(", ");
        return `<td>${e(x.fields.map((g) => g.field).join(", "))}</td><td class="num">${deg(f.azimuthDeg)}</td><td class="num">${deg(f.tiltDeg)}</td><td>${e(placements)}</td>`;
      }
      const list = x.fields.map((g) => `${e(g.field)} (${deg(g.azimuthDeg)} / ${deg(g.tiltDeg)})`).join("<br>");
      const placements = [...new Set(x.fields.map((g) => orient(g.moduleOrientation)))].join(", ");
      return `<td>${list}</td><td class="num mixed" colspan="2">${e(t("report.mixed"))}</td><td>${e(placements)}</td>`;
    };
    return `<div class="inv" data-inverter="${e(b.name)}">${head}
      <table><thead><tr><th class="num">MPPT</th><th>${e(t("stringTable.string"))}</th><th class="num">${e(t("stringTable.modules"))}</th><th>${e(t("report.field"))}</th><th class="num">${e(t("report.azimuth"))}</th><th class="num">${e(t("report.tilt"))}</th><th>${e(t("report.placement"))}</th></tr></thead>
      <tbody>${b.rows.map((x) => `<tr${x.mixed ? " data-mixed" : ""}><td class="num">${x.mppt}</td><td>${e(x.string)}</td><td class="num">${x.modules}</td>${cells(x)}</tr>`).join("")}</tbody></table></div>`;
  };
  const topoBody = m.inverters.length
    ? `${m.inverters.map(invTable).join("\n")}
      ${
        m.unassigned.length
          ? `<h3>${e(t("report.unassigned"))}</h3><table><thead><tr><th>${e(t("stringTable.string"))}</th><th class="num">${e(t("stringTable.modules"))}</th></tr></thead><tbody>${m.unassigned
              .map((x) => `<tr><td>${e(x.string)}</td><td class="num">${x.modules}</td></tr>`)
              .join("")}</tbody></table>`
          : ""
      }
      <p class="muted">${e(t("report.azimuthNote"))}</p>${anyMixed ? `<p class="muted">${e(t("report.mixedNote"))}</p>` : ""}`
    : `<p class="muted">${e(t("report.noInverters"))}</p>`;

  const sh = m.shading;
  const shadingRows =
    sh.lossKwh === null
      ? `<p data-shading="not-quantified">${e(t("report.shadingNotQuantified"))}</p>`
      : `<table data-shading="quantified"><tbody>
        <tr><th>${e(t("report.shadingLoss"))}</th><td class="num">${n0(sh.lossKwh)} kWh</td></tr>
        ${sh.unshadedKwh !== null ? `<tr><th>${e(t("report.shadingUnshaded"))}</th><td class="num">${n0(sh.unshadedKwh)} kWh</td></tr>` : ""}
        ${sh.unshadedKwh ? `<tr><th>${e(t("report.shadingShare"))}</th><td class="num">${n1((sh.lossKwh / sh.unshadedKwh) * 100)} %</td></tr>` : ""}
        ${sh.scope ? `<tr><th>${e(t("report.shadingScope"))}</th><td>${e(t(`report.scope_${sh.scope}`, { defaultValue: sh.scope }))}</td></tr>` : ""}
        ${sh.mismatchIncluded !== null ? `<tr><th>${e(t("report.shadingMismatch"))}</th><td>${e(t(sh.mismatchIncluded ? "report.included" : "report.notIncluded"))}</td></tr>` : ""}
        ${sh.method ? `<tr><th>${e(t("report.shadingMethod"))}</th><td><code>${e(sh.method)}</code></td></tr>` : ""}
      </tbody></table>
      ${sh.unshadedKwh === null && sh.lossKwh === 0 ? `<p class="muted">${e(t("report.shadingZeroNoBasis"))}</p>` : `<p class="muted">${e(t("report.shadingBoundary"))}</p>`}`;
  const shadingBody = `${shadingRows}<p class="pending" data-sunpath="pending">${e(t("report.sunPathPending"))}</p>`;

  const sldBody = `<figure>${r.sldSvg}<figcaption>${e(t("report.sldCaption"))}</figcaption></figure>`;

  const monthlyBody = !annual ? `<figure>${r.charts.monthly}</figure>
    <table data-period-monthly><thead><tr><th>${e(t("rpt2b2.month"))}</th><th class="num">${e(t("results.referenceProduction"))} (kWh)</th></tr></thead>
    <tbody>${m.monthlyAcKwh.map((value,index) => `<tr><td>${e(months[index])}</td><td class="num">${n1(value)}</td></tr>`).join("")}</tbody>
    <tfoot><tr><th>${e(t("rpt2b2.simulatedPeriod"))}</th><td class="num">${n1(energy)}</td></tr></tfoot></table>` : `<figure>${r.charts.monthly}</figure>
    <table><thead><tr>${months.map((x) => `<th class="num">${e(x)}</th>`).join("")}<th class="num">${e(t(annual ? "report.year" : "rpt2b2.simulatedPeriod"))}</th></tr></thead>
    <tbody><tr>${m.monthlyAcKwh.map((v) => `<td class="num">${n0(v)}</td>`).join("")}<td class="num">${n0(energy)}</td></tr></tbody></table>
    <p class="muted">${e(t("report.unitKwh"))}</p>`;

  const lossesBody = m.losses.length
    ? `${r.charts.waterfall ? `<figure>${r.charts.waterfall}</figure>` : ""}
      <table><thead><tr><th>${e(t("report.lossStage"))}</th><th>${e(t("report.lossGroup"))}</th><th class="num">${e(t("report.lossKwh"))}</th><th class="num">${e(t("report.remainingKwh"))}</th></tr></thead><tbody>
      <tr><td>${e(t("results.reference"))}</td><td></td><td></td><td class="num">${n0(m.referenceKwh ?? 0)}</td></tr>
      ${m.losses.map((l) => `<tr><td>${e(l.label)}</td><td>${e(l.stage)}</td><td class="num">${n0(l.lossKwh)}</td><td class="num">${n0(l.remainingKwh)}</td></tr>`).join("")}
      </tbody></table><p class="muted">${e(t("report.waterfallNote"))}</p>`
    : `<p class="muted">${e(t("results.noLedger"))}</p>`;

  const c = m.coverage;
  const heatBody = !annual ? `<p class="muted">${e(na)}</p>` :
    r.charts.heatmap && c
      ? `<figure>${r.charts.heatmap}<figcaption>${e(
          t("report.heatmapCaption", { shown: n0(c.weeklyShown), excluded: n0(c.weeklyExcluded), source: n0(c.sourceHours), missing: n0(c.missingHours) })
        )}</figcaption></figure>`
      : `<p class="muted">${e(t("report.heatmapUnavailable"))}</p>`;

  const checksBody = `<table><thead><tr><th>${e(t("report.rule"))}</th><th>${e(t("report.ruleState"))}</th><th>${e(t("report.ruleDetail"))}</th></tr></thead><tbody>${r.rules
    .map((x) => `<tr><td><code>${e(x.id)}</code></td><td class="rule-${x.state}">${e(t(`report.state_${x.state}`))}</td><td>${e(!annual && x.message === "not applicable to a partial period" ? na : x.message)}</td></tr>`)
    .join("")}</tbody></table>`;

  const ledgerBody = px?.result
    ? `<h3>${e(t("unc1.ledger"))}</h3><table data-report-ledger><tbody>${px.result.terms
        .map((x) => `<tr><td><code>${e(x.source_key)}</code></td><td>σ ${n0(x.sigma_kwh)} kWh</td></tr>`).join("")}
        <tr><td>${e(t("unc1.correlation"))}</td><td>${e(px.result.correlation_mode)}: ${e(px.result.correlation_basis)}</td></tr></tbody></table>`
    : "";
  const assumptionsBody = (m.assumptions.length
    ? `<table><tbody>${m.assumptions.map((a) => `<tr><td><code>${e(a.id)}</code></td><td>${e(a.severity)}</td><td>${e(a.statement)}</td></tr>`).join("")}</tbody></table>`
    : `<p class="muted">${e(t("results.noAssumptions"))}</p>`) + ledgerBody;

  const scopeBody = `<ul>
      <li>${e(t("report.scopeUncertainty"))}</li>
      <li>${e(t("report.scopeValidation"))}</li>
      <li>${e(t("report.scopeBoundary"))}</li>
      <li>${e(t("report.scopeSystem"))}</li>
      <li>${e(t(r.tier === "branded" ? "report.scopeBranded" : "report.scopeFree"))}</li>
    </ul>`;

  const body = [
    chapter("kpis", kpisBody),
    chapter("plan", planBody),
    chapter("topology", topoBody),
    chapter("sld", sldBody),
    chapter("shading", shadingBody),
    chapter("monthly", monthlyBody),
    chapter("losses", lossesBody),
    chapter("heatmap", heatBody),
    chapter("checks", checksBody),
    chapter("method", methodBody),
    chapter("assumptions", assumptionsBody),
    chapter("scope", scopeBody)
  ].join("\n");

  return `<!doctype html>
<html lang="${e(t("report.lang"))}">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; base-uri 'none'; form-action 'none'">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="RawiBumi">
<title>${e(t("report.title"))} · ${e(m.project)}</title>
<style>${r.css}</style>
</head>
<body data-tier="${r.tier}" data-authority="${m.authority}">
<main class="page"${r.charts.data ? ` data-report-chart-data="${e(JSON.stringify(r.charts.data))}"` : ""}>
${cover}
${body}
<footer class="rep-foot"><span>${e(t(r.tier === "branded" ? "report.footBranded" : "report.footFree"))}</span><span>${e(t("report.footFonts"))}</span></footer>
</main>
</body>
</html>
`;
}
