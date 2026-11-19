import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { engine } from "../client";
import { useStore } from "../state/store";
import { Button, Field, Section } from "../ui/kit";
import type { ShadingAccuracyPatch, SimulationRunRecord } from "../types";

export function ShadingAccuracyPanel() {
  const { state, dispatch, run } = useStore();
  const { t } = useTranslation();
  const view = state.view!;
  const settings = view.resolved_shading_accuracy;
  const [level, setLevel] = useState<"standard" | "high">(settings?.level ?? "standard");
  useEffect(() => { if (settings) setLevel(settings.level); }, [settings?.level, settings?.source, view.bundle.project.project_id]);
  if (!settings) return <p role="status">{t("s7d.defaultsUnavailable")}</p>;
  const busy = !!state.busy;
  async function save(patch: ShadingAccuracyPatch) {
    if (busy) return;
    const next = await run(t("sky1.saving"), () => engine.updateShadingAccuracy(view.bundle.project.project_id, patch));
    if (next) dispatch({ type: "setView", view: next });
  }
  return <Section title={t("sky1.title")}>
    <div data-shading-accuracy={settings.level}>
      <p className="note">{t("sky1.help")}</p>
      <Field label={t("sky1.title")}><select className="input" aria-label={t("sky1.title")} value={level} disabled={busy} onChange={e => setLevel(e.target.value as "standard" | "high")}>
        <option value="standard">{t("sky1.standard")}</option><option value="high">{t("sky1.high")}</option>
      </select></Field>
      <p>{t(`sky1.${settings.source}`)}</p>
      <div className="row">
        <Button disabled={busy || level === settings.level} onClick={() => void save({ overrides: { level } })}>{t("sky1.save")}</Button>
        <Button disabled={busy || settings.source !== "project_override"} onClick={() => void save({ reset_to_recommended_defaults: true })}>{t("sky1.reset")}</Button>
      </div>
    </div>
  </Section>;
}

const record = (value: unknown): Record<string, unknown> | undefined => value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
function numbers(value: unknown, keys: string[]): number[] | undefined {
  const obj = record(value);
  const values = keys.map(key => obj?.[key]);
  return values.every(n => typeof n === "number" && Number.isFinite(n) && n > 0) ? values as number[] : undefined;
}

/** Read only immutable run evidence. Never substitute the current project. */
export function recordedShadingSampling(run: SimulationRunRecord) {
  const snapshot = run.resolved_shading_accuracy;
  const runtime = record(record(run.model_manifest)?.near_shading_runtime);
  const sky = snapshot?.sky_dome_resolution ?? record(runtime?.sky_solver_manifest)?.resolution;
  const ground = snapshot?.ground_dome_resolution ?? record(runtime?.ground_solver_manifest)?.resolution;
  const skyValues = numbers(sky, ["azimuth_sectors", "elevation_bands", "horizon_azimuth_sectors", "horizon_elevation_bands", "horizon_band_elevation_deg"]);
  const groundValues = numbers(ground, ["azimuth_sectors", "depression_bands"]);
  return skyValues && groundValues ? { sky: skyValues, ground: groundValues, snapshot } : undefined;
}

export function RunShadingAccuracy({ run }: { run: SimulationRunRecord }) {
  const { t } = useTranslation();
  const sampling = recordedShadingSampling(run);
  if (!sampling) return <p>{t("sky1.unrecorded")}</p>;
  const { sky, ground, snapshot } = sampling;
  return <details data-run-shading-accuracy={snapshot?.level ?? "legacy"}>
    <summary>{t("sky1.runSettings")} · {t(snapshot ? `sky1.${snapshot.level}` : "sky1.legacy")}</summary>
    <dl>
      <dt>{t("sky1.sky")}</dt><dd>{sky[0]} × {sky[1]}</dd>
      <dt>{t("sky1.horizon")}</dt><dd>{sky[2]} × {sky[3]} · {sky[4]}°</dd>
      <dt>{t("sky1.ground")}</dt><dd>{ground[0]} × {ground[1]}</dd>
    </dl>
    <p>{snapshot ? `${snapshot.defaults_id} · ${t(`sky1.${snapshot.source}`)} · ${t(`sky1.${snapshot.ground_source}`)}` : t("sky1.unknownSource")}</p>
  </details>;
}
