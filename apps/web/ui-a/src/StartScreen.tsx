import { FormEvent, useMemo, useState } from "react";
import { DEMO, engine } from "./client";
import { MapWorkspace } from "./MapWorkspace";
import type { Catalog, ProjectSummary, ProjectView, WorkspaceMode } from "./types";
import { Button, Field, NumberInput, Select } from "./ui/kit";


export function StartScreen({ projects, catalog, onOpen, onCreated, busy }: { projects: ProjectSummary[]; catalog: Catalog | null; onOpen: (id: string) => void; onCreated: (v: ProjectView) => void; busy: boolean }) {
  const [name, setName] = useState("New PV study");
  const [lat, setLat] = useState(-6.2);
  const [lon, setLon] = useState(106.82);
  const [elev, setElev] = useState(0);
  const [tz, setTz] = useState(Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC");
  const [mode, setMode] = useState<WorkspaceMode>("blank_engineering_plane");
  const empty = useMemo(() => ({ type: "FeatureCollection", features: [] }) as never, []);


  async function submit(e: FormEvent) {
    e.preventDefault();
    onCreated(await engine.createProject({ name, latitude_deg: lat, longitude_deg: lon, elevation_m: elev, timezone: tz, workspace_mode: mode }));
  }


  return (
    <main className="start">
      <section className="start__intro">
        <h1>RawiBumi</h1>
        <p>Draw the site, lay out the array, wire it, and simulate — with every value traceable to where it came from.</p>
        <div className="start__meta">
          {catalog ? `${catalog.modules.length} modules and ${catalog.inverters.length} inverters in the library` : "Loading component library…"}
          {DEMO && <span className="demo-flag">Demo engine</span>}
        </div>
      </section>
      <section className="start__grid">
        <form className="start__card" onSubmit={(e) => void submit(e)}>
          <h2>New project</h2>
          <Field label="Project name">
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} required />
          </Field>
          <div className="grid2">
            <Field label="Latitude" unit="°">
              <NumberInput value={lat} step={0.000001} min={-90} max={90} onChange={setLat} />
            </Field>
            <Field label="Longitude" unit="°">
              <NumberInput value={lon} step={0.000001} min={-180} max={180} onChange={setLon} />
            </Field>
            <Field label="Elevation" unit="m">
              <NumberInput value={elev} step={0.1} onChange={setElev} />
            </Field>
            <Field label="Timezone (IANA)">
              <input className="input" value={tz} onChange={(e) => setTz(e.target.value)} required />
            </Field>
          </div>
          <Field label="Start in">
            <Select
              value={mode}
              onChange={setMode}
              options={[
                { value: "blank_engineering_plane", label: "Blank engineering plane" },
                { value: "map_overlay", label: "Map overlay" }
              ]}
            />
          </Field>
          <Button tone="primary" type="submit" disabled={busy}>
            Create project
          </Button>
        </form>
        <div className="start__card start__card--map">
          <h2>Pick the site</h2>
          <p className="sub">Click the map to set coordinates, or type them.</p>
          <MapWorkspace compact site={{ latitude_deg: lat, longitude_deg: lon, elevation_m: null, timezone: tz, north_reference: "geodetic_true_north" }} geojson={empty} onCoordinatePick={(a, b) => { setLat(Number(a.toFixed(6))); setLon(Number(b.toFixed(6))); }} />
        </div>
      </section>
      <section className="start__recent">
        <h2>
          Saved projects <span className="count">{projects.length}</span>
        </h2>
        {projects.length === 0 && <div className="empty">No saved projects in this store yet.</div>}
        <div className="start__list">
          {projects.map((p) => (
            <button key={p.project_id} type="button" className="start__row" onClick={() => onOpen(p.project_id)}>
              <strong>{p.name}</strong>
              <span>
                {p.latitude_deg.toFixed(5)}, {p.longitude_deg.toFixed(5)}
              </span>
              <span>{p.timezone}</span>
            </button>
          ))}
        </div>
      </section>
    </main>
  );
}