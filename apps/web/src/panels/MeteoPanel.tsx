import { useEffect, useState } from "react";
import { engine } from "../client";
import { useTranslation } from "react-i18next";
import type { WeatherSource } from "../types";
import { useForm, useStore } from "../state/store";
import { Button, Field, FieldGroup, Kv, NotWired, Section, Segmented, Select } from "../ui/kit";

export function MeteoPanel({ onImport }: { onImport: () => void }) {
  const { state, dispatch, run, toast } = useStore();
  const v = state.view!;
  const pid = v.bundle.project.project_id;
  const [sources, setSources] = useState<WeatherSource[]>([]);
  const [wx, setWx] = useForm("meteo.acquire", { source: "", start: "2025-01-01", end: "2025-12-31" });
  const { t } = useTranslation();
  useEffect(() => {
    engine
      .weatherSources()
      .then((s) => {
        setSources(s);
        if (!wx.source && s[0]) setWx({ ...wx, source: s[0].source_id });
      })
      .catch(() => setSources([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const sel = v.bundle.weather_selection;

  return (
    <>
      <p className="note">{t("stepIntros.weatherCaveat")}</p>
      <Section primary title={t("sections.weather")}>
        {sel ? (
          <Kv
            rows={[
              ["Dataset", sel.name ?? sel.source_id ?? sel.revision_id],
              ["Period", `${sel.start_time?.slice(0, 10) ?? "—"} → ${sel.end_time?.slice(0, 10) ?? "—"}`],
              ["QC", sel.data_quality_status ?? "unknown"],
              ["Revision", sel.revision_id],
              ...(sel.manifest?.kind === "file_import" ? [
                [t("s12b.filename"), String(sel.manifest.filename ?? "—")],
                [t("s12b.format"), String(sel.manifest.format ?? "—")]
              ] as [string, string][] : [])
            ]}
          />
        ) : (
          <div className="issue issue--blocking">No weather dataset. Acquire one or import a file.</div>
        )}
        <Field label="Source product">
          <Select value={wx.source} onChange={(source) => setWx({ ...wx, source })} options={sources.map((s) => ({ value: s.source_id, label: s.label }))} />
        </Field>
        <div className="grid2">
          <Field label="Start">
            <input className="input" type="date" value={wx.start} onChange={(e) => setWx({ ...wx, start: e.target.value })} />
          </Field>
          <Field label="End">
            <input className="input" type="date" value={wx.end} onChange={(e) => setWx({ ...wx, end: e.target.value })} />
          </Field>
        </div>
        <div className="row">
          <Button
            small
            tone="primary"
            disabled={!wx.source}
            onClick={async () => {
              const r = await run("Acquiring weather", async () => {
                await engine.acquireWeather(pid, { source_id: wx.source, start_date: wx.start, end_date: wx.end });
                return engine.project(pid);
              });
              if (r) {
                dispatch({ type: "setView", view: r });
                toast("ok", "Weather revision pinned.");
              }
            }}
          >
            Acquire
          </Button>
          <Button small onClick={onImport}>
            Import TMY3 / EPW / MET CSV…
          </Button>
        </div>
        <FieldGroup label={t("s7d.timestep")} unit="min">
          <Segmented label={t("s7d.timestep")} value="60" onChange={() => undefined} options={["1", "5", "15", "60"].map((value) => ({ value, label: value === "60" ? t("s7d.hourly") : value, disabled: value !== "60" }))} />
          <NotWired id="subHourlyTimestep" compact />
        </FieldGroup>
        <p className="note">{t("s7d.hourlyNote")}</p>
      </Section>
    </>
  );
}
