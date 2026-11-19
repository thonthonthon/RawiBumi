import { useStore } from "../state/store";
import { Field, Kv, NotWired, NumberInput, PendingBlock, Section, Segmented, Select } from "../ui/kit";

export function SitePanel() {
  const { state, dispatch } = useStore();
  const v = state.view!;
  const site = v.bundle.project.site;
  const u = state.underlay;
  return (
    <>
      <Section title="Site" aside={<NotWired id="siteEdit" compact />}>
        <div className="grid2">
          <Field label="Latitude" unit="°">
            <NumberInput value={site.latitude_deg} onChange={() => undefined} step={0.000001} />
          </Field>
          <Field label="Longitude" unit="°">
            <NumberInput value={site.longitude_deg} onChange={() => undefined} step={0.000001} />
          </Field>
          <Field label="Elevation" unit="m">
            <NumberInput value={site.elevation_m ?? 0} onChange={() => undefined} />
          </Field>
          <Field label="Timezone (IANA)">
            <input className="input" value={site.timezone} readOnly />
          </Field>
        </div>
        <Kv
          rows={[
            ["North reference", "Geodetic true north"],
            ["Local frame", "X east · Y north · Z up (m)"],
            ["Azimuth convention", <span key="az">Shown on every angle input <NotWired id="siteEdit" compact /></span>]
          ]}
        />
      </Section>

      <Section title="Imagery underlay">
        <p className="note">Imagery is context only. Matching it to actual site conditions is your responsibility; typed or surveyed dimensions always override traced ones.</p>
        <Segmented
          value={u.kind}
          onChange={(kind) => dispatch({ type: "setUnderlay", patch: { kind } })}
          options={[
            { value: "none", label: "Blank plane" },
            { value: "tiles", label: "Tile provider" },
            { value: "image", label: "Uploaded image" }
          ]}
        />
        {u.kind === "tiles" && (
          <div className="stack">
            <Field label="Tile URL template" hint="Use {z}/{x}/{y}; {key} is replaced by the API key. Check the provider's licence terms.">
              <input
                className="input"
                placeholder="https://…/{z}/{y}/{x}?key={key}"
                value={u.tileUrl}
                onChange={(e) => dispatch({ type: "setUnderlay", patch: { tileUrl: e.target.value } })}
              />
            </Field>
            <div className="grid2">
              <Field label="API key (optional)">
                <input className="input" type="password" value={u.apiKey} onChange={(e) => dispatch({ type: "setUnderlay", patch: { apiKey: e.target.value } })} />
              </Field>
              <Field label="Attribution">
                <input className="input" value={u.tileAttribution} onChange={(e) => dispatch({ type: "setUnderlay", patch: { tileAttribution: e.target.value } })} />
              </Field>
            </div>
          </div>
        )}
        {u.kind === "image" && (
          <div className="stack">
            <Field label="Aerial image or drawing">
              <input
                className="input"
                type="file"
                accept="image/*"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  const r = new FileReader();
                  r.onload = () => dispatch({ type: "setUnderlay", patch: { imageDataUrl: String(r.result), imageName: file.name } });
                  r.readAsDataURL(file);
                }}
              />
            </Field>
            <Field label="Registration method">
              <Select
                value={u.registration}
                onChange={(registration) => dispatch({ type: "setUnderlay", patch: { registration } })}
                options={[
                  { value: "scale", label: "Scale only (2 points + known distance)" },
                  { value: "similarity", label: "Similarity (2 control points)" },
                  { value: "perspective", label: "Perspective (4 control points)" }
                ]}
              />
            </Field>
            <div className="grid2">
              <Field label="Ground resolution" unit="m/px">
                <NumberInput value={u.imageMetersPerPixel} step={0.001} min={0.001} onChange={(imageMetersPerPixel) => dispatch({ type: "setUnderlay", patch: { imageMetersPerPixel } })} />
              </Field>
              <Field label="Rotation" unit="° ccw">
                <NumberInput value={u.imageRotationDeg} step={0.1} onChange={(imageRotationDeg) => dispatch({ type: "setUnderlay", patch: { imageRotationDeg } })} />
              </Field>
              <Field label="Top-left X" unit="m">
                <NumberInput value={u.imageOffset[0]} onChange={(x) => dispatch({ type: "setUnderlay", patch: { imageOffset: [x, u.imageOffset[1]] } })} />
              </Field>
              <Field label="Top-left Y" unit="m">
                <NumberInput value={u.imageOffset[1]} onChange={(y) => dispatch({ type: "setUnderlay", patch: { imageOffset: [u.imageOffset[0], y] } })} />
              </Field>
            </div>
            <PendingBlock id="imageryConfig" note="Picking control points on the canvas and saving registration with the project arrive with this endpoint. Manual transform above works now (session only).">
              <button className="btn btn--sm" type="button" disabled>
                Pick control points on canvas
              </button>
            </PendingBlock>
          </div>
        )}
        {u.kind !== "none" && (
          <Field label="Opacity">
            <input type="range" min={0.1} max={1} step={0.05} value={u.opacity} onChange={(e) => dispatch({ type: "setUnderlay", patch: { opacity: Number(e.target.value) } })} />
          </Field>
        )}
      </Section>
    </>
  );
}
