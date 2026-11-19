import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { engine } from "../client";
import type { SiteChanges } from "../types";
import i18n from "../i18n";
import { ModalDialog } from "../ui/ModalDialog";
import { AddressSection } from "../site/AddressSection";
import { ImagerySection } from "../imagery/ImagerySection";
import { SystemSection } from "../site/SystemSection";
import { useStore } from "../state/store";
import { Button, Field, Kv, Section } from "../ui/kit";

export function siteValidation(values: { latitude_deg: number; longitude_deg: number; elevation_m: number; timezone: string; name: string }) {
  const errors: Record<string, string> = {};
  if (!Number.isFinite(values.latitude_deg) || Math.abs(values.latitude_deg) >= 90) errors.latitude_deg = i18n.t("s7d.latitudeError");
  if (!Number.isFinite(values.longitude_deg) || Math.abs(values.longitude_deg) > 180) errors.longitude_deg = i18n.t("s7d.longitudeError");
  if (!Number.isFinite(values.elevation_m) || values.elevation_m < -500 || values.elevation_m > 9000) errors.elevation_m = i18n.t("s7d.elevationError");
  if (!values.name.trim() || values.name.trim().length > 160) errors.name = i18n.t("s7d.nameError");
  // Resolve IANA aliases first: supportedValuesOf omits UTC and some valid aliases.
  if (typeof Intl.supportedValuesOf === "function") {
    try {
      const canonical = new Intl.DateTimeFormat("en", { timeZone: values.timezone }).resolvedOptions().timeZone;
      if (canonical !== "UTC" && !Intl.supportedValuesOf("timeZone").includes(canonical)) errors.timezone = i18n.t("s7d.timezoneError");
    } catch { errors.timezone = i18n.t("s7d.timezoneError"); }
  }
  if (!values.timezone.trim()) errors.timezone = i18n.t("s7d.timezoneError");
  return errors;
}

export function changedSiteKeys(site: Omit<SiteChanges, "elevation_m"> & { elevation_m?: number | null }, draft: Required<SiteChanges>): SiteChanges {
  return Object.fromEntries(Object.entries(draft).filter(([key, value]) => (site[key as keyof SiteChanges] ?? (key === "name" ? "" : key === "elevation_m" ? 0 : undefined)) !== value));
}
export function needsWeatherConfirmation(changes: SiteChanges, pinned: boolean): boolean {
  return pinned && Object.keys(changes).some((key) => key !== "name");
}

export function SitePanel() {
  const { state, dispatch, run } = useStore();
  const { t } = useTranslation();
  const v = state.view!;
  const site = v.bundle.project.site;
  const initial = { name: site.name ?? "", latitude_deg: String(site.latitude_deg), longitude_deg: String(site.longitude_deg), elevation_m: String(site.elevation_m ?? 0), timezone: site.timezone };
  const [draft, setDraft] = useState(initial);
  const [confirmation, setConfirmation] = useState<SiteChanges | null>(null);
  useEffect(() => { setDraft(initial); setConfirmation(null); }, [site.name, site.latitude_deg, site.longitude_deg, site.elevation_m, site.timezone, v.bundle.project.project_id]);
  const values = { name: draft.name.trim(), latitude_deg: draft.latitude_deg.trim() ? Number(draft.latitude_deg) : NaN,
    longitude_deg: draft.longitude_deg.trim() ? Number(draft.longitude_deg) : NaN,
    elevation_m: draft.elevation_m.trim() ? Number(draft.elevation_m) : NaN, timezone: draft.timezone.trim() };
  const errors = siteValidation(values);
  const changes = changedSiteKeys(site, values);
  async function save(patch: SiteChanges, confirmed = false) {
    const updated = await run(t("s7d.savingSite"), () => engine.updateSite(v.bundle.project.project_id, patch, confirmed ? { clear_weather_selection: true } : undefined));
    if (updated) { dispatch({ type: "setView", view: updated }); setConfirmation(null); }
  }
  return (
    <>
      <Section primary title={t("sections.location")}>
        <div className="grid2">
          {(["name", "latitude_deg", "longitude_deg", "elevation_m", "timezone"] as const).map((key) => (
            <Field key={key} label={t(`s7d.${key}`)}>
              <input className="input" value={draft[key]} aria-invalid={!!errors[key]} aria-describedby={errors[key] ? `site-${key}-error` : undefined}
                onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} />
              {errors[key] && <span id={`site-${key}-error`} className="form-error" role="alert">{errors[key]}</span>}
            </Field>
          ))}
        </div>
        <div className="row">
          <Button disabled={!!state.busy || !!Object.keys(errors).length || !Object.keys(changes).length} onClick={() => {
            if (needsWeatherConfirmation(changes, !!v.bundle.weather_selection)) setConfirmation(changes);
            else void save(changes);
          }}>{t("s7d.apply")}</Button>
          <Button disabled={!!state.busy} onClick={() => setDraft(initial)}>{t("s7d.reset")}</Button>
        </div>
        {confirmation && <ModalDialog alert label={t("s7d.clearWeather")} onClose={() => !state.busy && setConfirmation(null)}>
          <h2>{t("s7d.clearWeather")}</h2>
          <p>{t("s7d.weatherConfirmation", { revision: v.bundle.weather_selection?.revision_id })}</p>
          <div className="row"><Button cancel disabled={!!state.busy} onClick={() => setConfirmation(null)}>{t("s7d.cancel")}</Button>
            <Button disabled={!!state.busy} onClick={() => void save(confirmation, true)}>{t("s7d.confirmSite")}</Button></div>
        </ModalDialog>}
        <Kv
          rows={[
            ["North reference", "Geodetic true north"],
            ["Local frame", "X east · Y north · Z up (m)"],
            ["Azimuth convention", "Shown on every angle input"]
          ]}
        />
        <AddressSection />
      </Section>

      <SystemSection />

      <ImagerySection />
    </>
  );
}
