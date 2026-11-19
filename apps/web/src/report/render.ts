import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import archivo400 from "@fontsource/archivo/files/archivo-latin-400-normal.woff2?inline";
import archivo600 from "@fontsource/archivo/files/archivo-latin-600-normal.woff2?inline";
import osifont from "/fonts/osifont/osifont-lgpl3fe.woff?url&inline";
import tokensCss from "../ui/tokens.css?raw";
import reportCss from "./report.css?raw";
import { SldSvg } from "./pureSld";
import { layoutSld } from "../electrical/sldLayout";
import { heatmapOption, monthlyOption, paletteFromTokens, waterfallOption, MONTH_KEYS } from "../results/chartOptions";
import { optionToSvg } from "../results/echarts";
import { isCompleteYearResult, modelFingerprint, reportModel, type Authority } from "../results/model";
import { EMPTY_SYSTEM } from "./presentation";
import type { AnnualPxxView } from "../types";
import type { VerifiedReportSnapshot } from "./snapshot";
import { renderReportHtml, type ReportTier } from "./template";
import { createInstance } from "i18next";
import { en } from "../i18n/en";
import { id } from "../i18n/id";

/** The report's inline CSS: embedded fonts, the shared tokens, the report sheet. */
export function reportCssText(): string {
  const faces = [
    `@font-face{font-family:"Archivo";font-weight:400;src:url(${archivo400}) format("woff2")}`,
    `@font-face{font-family:"Archivo";font-weight:600;src:url(${archivo600}) format("woff2")}`,
    `@font-face{font-family:"osifont";font-weight:400;src:url(${osifont}) format("woff")}`
  ].join("\n");
  return `${faces}\n${tokensCss}\n${reportCss}`;
}

/** YYYY-MM-DD of `d` in an IANA timezone; UTC if the zone is unknown to this browser. */
export function dateInZone(d: Date, timeZone: string): string {
  try {
    return new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).format(d);
  } catch {
    return d.toISOString().slice(0, 10);
  }
}

export interface RenderOptions {
  locale: "en" | "id";
  planFigurePng: string | null;
  watermark?: "free_community";
  tier?: ReportTier;
  branding?: string;
  authority?: Authority;
}

export function renderReportDetails(source: VerifiedReportSnapshot, options: RenderOptions): { html: string; fingerprint: string } {
  if (options.locale !== "en" && options.locale !== "id") throw new Error("locale must be en or id");
  const translator = createInstance();
  void translator.init({ resources: { en: { translation: en }, id: { translation: id } }, lng: options.locale, fallbackLng: "en", initAsync: false, interpolation: { escapeValue: false } });
  const t = (key: string, opts?: Record<string, unknown>) => String(translator.t(key, opts));
  const original = source.design_view;
  const run = original.bundle.simulation_runs.find(run => run.simulation_run_id === source.identity.simulation_run_id);
  if (!run) throw new Error("Snapshot run identity is missing");
  const view = { ...original, bundle: { ...original.bundle, simulation_runs: [{ ...run, summary_result: source.summary }] } };
  const { model, rules } = reportModel(view, run.simulation_run_id, { authority: options.authority ?? "ENGINE", hourlyAcKw: source.hourly_ac.values?.map(row => row.map(value => value ?? NaN)) ?? null, periodAware: true, t });
  const annual = isCompleteYearResult(model);
  const px = source.annual_pxx;
  const annualPxx: AnnualPxxView | null = annual && px.status !== "no_uncertainty_ledger" ? {
    schema_name: "AnnualPxxView", run_id: run.simulation_run_id, status: px.status === "available" ? "available" : "unavailable",
    reasons: px.reasons ?? [], basis: px.basis!, ledger_sha256: px.ledger_sha256 ?? null, result: px.result ?? null, label: px.label!,
    P99: { status: "unavailable", reason: px.P99_reason, message: px.P99_message }
  } : null;
  const completion = new Date("completed_at" in run && typeof run.completed_at === "string" ? run.completed_at : "");
  if (!Number.isFinite(completion.getTime())) throw new Error("Snapshot completion time is unavailable");
  const site = source.site;
  const planFigure = options.planFigurePng ? { png: options.planFigurePng, width: 900, height: 540 } : null;
  if (planFigure && !/^data:image\/png;base64,[A-Za-z0-9+/]+=*$/.test(planFigure.png)) throw new Error("Invalid report plan PNG");
  const p = paletteFromTokens();
  const months = annual ? MONTH_KEYS.map((k) => t(`results.month_${k}`)) : source.summary.monthly_energy.map(row => row.month);
  const monthlyConfig = monthlyOption(p, { months, series: [{ name: t("results.referenceProduction"), values: model.monthlyAcKwh }], unit: "kWh", aria: t("results.monthlyAria") });
  const monthly = optionToSvg(monthlyConfig, 720, 280);
  const waterfallConfig = model.losses.length ? waterfallOption(p, {
    start: { label: t("results.reference"), value: model.referenceKwh ?? 0 },
    losses: model.losses.map(loss => ({ label: loss.label, value: loss.lossKwh })),
    end: { label: t("results.referenceProduction"), value: model.periodAcKwh },
    unit: "kWh", aria: t("results.waterfallAria")
  }) : null;
  const waterfall = waterfallConfig ? optionToSvg(waterfallConfig, 720, 340) : null;
  const heatmapConfig = annual && model.heatmap52 ? heatmapOption(p, { values: model.heatmap52, unit: "kW", hourLabel: t("results.hour"), weekLabel: t("results.week"), aria: t("results.heatmapAria") }) : null;
  const heatmap = heatmapConfig ? optionToSvg(heatmapConfig, 720, 300) : null;

  const layout = layoutSld(view, t);
  const sldSvg = renderToStaticMarkup(createElement(SldSvg, { layout, ariaLabel: t("sld.ariaLabel", { nodes: layout.nodes.length }), stateLabel: state => t(`checks.state_${state}`) }));
  const fingerprint = modelFingerprint(model);
  const watermark = options.watermark === "free_community" ? t("rpt2b2.watermark") : null;
  const css = reportCssText() + (watermark ? `\n@page { margin-top:16mm; @top-center { content: "${watermark}"; font-family:Archivo,sans-serif; font-size:9pt; color:color-mix(in srgb,var(--rb-color-paper-ink) 45%,transparent); } }` : "");
  const html = renderReportHtml({
    imported: "origin" in run && run.origin === "imported",
    model, rules, tier: options.tier ?? "free", branding: options.branding ?? "", planFigure, sldSvg,
    charts: { monthly, waterfall, heatmap, data: { monthly: monthlyConfig.series, waterfall: waterfallConfig?.series ?? null, heatmap: heatmapConfig?.series ?? null } }, annualPxx, verifiedSource: source, fingerprint,
    generatedAt: new Intl.DateTimeFormat("en-CA", { timeZone: site.timezone, dateStyle: "medium", timeStyle: "short", hourCycle: "h23" }).format(completion) + ` ${site.timezone}`,
    identity: { address: site.address?.text.trim() || null, addressAttribution: site.address?.attribution || null,
      latitude: site.latitude_deg, longitude: site.longitude_deg, elevationM: site.elevation_m ?? null,
      issuedOn: dateInZone(completion, site.timezone), system: { ...EMPTY_SYSTEM, ...site.installation } },
    css, t, periodAware: true
  });
  return { html, fingerprint };
}

/** Shared screen/PDF renderer; all scientific values come from the verified snapshot. */
export function renderReport(source: VerifiedReportSnapshot, options: RenderOptions): string {
  return renderReportDetails(source, options).html;
}
