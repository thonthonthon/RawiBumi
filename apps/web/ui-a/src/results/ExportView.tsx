import { useForm, useStore } from "../state/store";
import { Check, Field, NotWired, Paid, Segmented, Select, Button } from "../ui/kit";

interface Col {
  id: string;
  label: string;
  unit: string;
  group: string;
  tier: "free" | "pro";
}

const COLUMNS: Col[] = [
  { id: "ghi", label: "GHI", unit: "W/m²", group: "Meteo", tier: "free" },
  { id: "dhi", label: "DHI", unit: "W/m²", group: "Meteo", tier: "free" },
  { id: "dni", label: "DNI", unit: "W/m²", group: "Meteo", tier: "free" },
  { id: "tamb", label: "Ambient temperature", unit: "°C", group: "Meteo", tier: "free" },
  { id: "wind", label: "Wind speed", unit: "m/s", group: "Meteo", tier: "free" },
  { id: "poa", label: "POA irradiance (proposed)", unit: "W/m²", group: "Meteo", tier: "free" },
  { id: "p_dc", label: "DC power", unit: "kW", group: "PV", tier: "free" },
  { id: "p_ac_pre", label: "AC power before zero export", unit: "kW", group: "PV", tier: "free" },
  { id: "p_ac_post", label: "AC power after zero export", unit: "kW", group: "PV", tier: "free" },
  { id: "p_curt", label: "Curtailed power (proposed)", unit: "kW", group: "PV", tier: "free" },
  { id: "load", label: "Load (uploaded, aligned)", unit: "kW", group: "Load", tier: "free" },
  { id: "p_string", label: "String / MPPT production", unit: "kW", group: "Detail", tier: "pro" },
  { id: "rst", label: "RST phase balance", unit: "kW", group: "Detail", tier: "pro" },
  { id: "tcell", label: "Cell temperature", unit: "°C", group: "Detail", tier: "pro" },
  { id: "losses", label: "All intermediate losses", unit: "kW", group: "Detail", tier: "pro" }
];

export function ExportView() {
  const { state, toast } = useStore();
  const v = state.view!;
  const runs = v.bundle.simulation_runs;
  const run = runs[runs.length - 1];
  const [spec, setSpec] = useForm("export.spec", {
    resolution: "hourly",
    format: "csv",
    level: "project",
    cols: COLUMNS.filter((c) => c.tier === "free" && !c.label.includes("proposed")).map((c) => c.id)
  });
  const groups = [...new Set(COLUMNS.map((c) => c.group))];
  const selected = COLUMNS.filter((c) => spec.cols.includes(c.id));
  const rowsPerYear = spec.resolution === "hourly" ? 8760 : 525600;
  const bytes = rowsPerYear * (selected.length + 1) * 10;

  const manifest = {
    run_id: run?.simulation_run_id ?? null,
    input_hash: run?.input_hash ?? null,
    project_revision_id: run?.project_revision_id ?? null,
    scene_revision_id: run?.scene_revision_id ?? null,
    electrical_revision_id: run?.electrical_revision_id ?? null,
    weather_dataset_revision_id: run?.weather_dataset_revision_id ?? null,
    load_revision_id: null,
    timestamp_convention: "interval_start",
    timezone: v.bundle.project.site.timezone,
    resolution: spec.resolution === "hourly" ? "PT1H" : "run_native",
    aggregation: { energy: "sum", power_irradiance_temperature: "mean" },
    meteo_temporal_origin: "from weather revision manifest",
    curtailment_resolution: "finest common of simulation and load",
    columns: selected.map((c) => ({ id: c.id, unit: c.unit })),
    assumptions: (run?.assumptions ?? []).map((a) => a.assumption_id)
  };

  return (
    <div className="results">
      <header className="results__head">
        <div>
          <h2>Export</h2>
          <div className="sub">A ZIP with CSV (or Parquet) and a JSON manifest. Files without the manifest are not reproducible.</div>
        </div>
      </header>
      {!run ? (
        <div className="empty">Run a simulation first.</div>
      ) : (
        <div className="export-grid">
          <div className="panel-card">
            <Field label="Resolution">
              <Segmented
                value={spec.resolution}
                onChange={(resolution) => setSpec({ ...spec, resolution })}
                options={[
                  { value: "hourly", label: "Hourly" },
                  { value: "native", label: "Run native (sub-hourly)", title: "Only when the run itself was sub-hourly" }
                ]}
              />
            </Field>
            <div className="grid2">
              <Field label="Format">
                <Select value={spec.format} onChange={(format) => setSpec({ ...spec, format })} options={[{ value: "csv", label: "CSV" }, { value: "parquet", label: "Parquet" }]} />
              </Field>
              <Field label="Aggregation level">
                <Select
                  value={spec.level}
                  onChange={(level) => setSpec({ ...spec, level })}
                  options={[
                    { value: "project", label: "Project" },
                    { value: "inverter", label: "Per inverter — Pro", disabled: true },
                    { value: "mppt", label: "Per MPPT / string — Pro", disabled: true }
                  ]}
                />
              </Field>
            </div>
            {groups.map((g) => (
              <fieldset className="colgroup" key={g}>
                <legend>
                  {g} {g === "Detail" && <Paid what="Detailed export" />}
                </legend>
                {COLUMNS.filter((c) => c.group === g).map((c) => (
                  <Check
                    key={c.id}
                    disabled={c.tier === "pro"}
                    checked={spec.cols.includes(c.id)}
                    onChange={(on) => setSpec({ ...spec, cols: on ? [...spec.cols, c.id] : spec.cols.filter((x) => x !== c.id) })}
                    label={
                      <>
                        {c.label} <span className="sub">{c.unit}</span>
                      </>
                    }
                  />
                ))}
              </fieldset>
            ))}
            <div className="sizeline">
              {rowsPerYear.toLocaleString()} rows × {selected.length + 1} columns ≈ {(bytes / 1e6).toFixed(bytes > 1e8 ? 0 : 1)} MB per year (estimate)
            </div>
            <div className="row">
              <Button tone="primary" onClick={() => toast("pending", "Export needs POST /runs/{run_id}/exports (server-side generation). Not wired yet.")}>
                Generate export
              </Button>
              <NotWired id="exportBundle" compact />
            </div>
          </div>
          <div className="panel-card">
            <div className="panel-card__title">Manifest preview</div>
            <pre className="manifest">{JSON.stringify(manifest, null, 2)}</pre>
          </div>
        </div>
      )}
    </div>
  );
}
