import { useEffect, useState } from "react";
import { useStore } from "./state/store";
import { Button, NotWired } from "./ui/kit";


const CATEGORIES = [
  { id: "components", label: "Components", formats: ".PAN, .OND, module.csv, inverter.csv, *-advanced.yaml", accept: ".pan,.ond,.csv,.yaml,.yml", note: "Lossless parse, then field-mapping preview before commit." },
  { id: "meteo", label: "Weather", formats: "TMY3, EPW, Meteonorm DAT, PVsyst standard CSV, native CSV", accept: ".csv,.epw,.dat,.tm3,.txt", note: "Binary PVsyst .MET is detected but not decoded." },
  { id: "geometry", label: "Geometry", formats: "SketchUp COLLADA (.dae), PVsyst .SHD, glTF/GLB, OBJ", accept: ".dae,.shd,.glb,.gltf,.obj", note: "PV faces identified by material name (e.g. PV_*); units and axes confirmed with a bounding-box preview." },
  { id: "horizon", label: "Horizon", formats: "CSV azimuth/elevation, PVsyst .HOR", accept: ".csv,.hor", note: "Far shading is reported separately from near shading." },
  { id: "load", label: "Load profile", formats: "CSV timestamp, value", accept: ".csv,.txt", note: "Units, timestamp convention and timezone are declared, never inferred." }
];


export function ImportHub({ onClose, initial = "components" }: { onClose: () => void; initial?: string }) {
  const [cat, setCat] = useState(initial);
  const [file, setFile] = useState<File | null>(null);
  const c = CATEGORIES.find((x) => x.id === cat)!;
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" role="dialog" aria-label="Import" onClick={(e) => e.stopPropagation()}>
        <header className="modal__head">
          <h3>Import</h3>
          <button className="iconbtn" type="button" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>
        <div className="modal__body import">
          <nav className="import__nav">
            {CATEGORIES.map((x) => (
              <button key={x.id} type="button" className={x.id === cat ? "import__cat import__cat--on" : "import__cat"} onClick={() => { setCat(x.id); setFile(null); }}>
                {x.label}
              </button>
            ))}
          </nav>
          <div className="import__main">
            <div className="import__formats">{c.formats}</div>
            <p className="note">{c.note}</p>
            <label className="dropzone">
              <input type="file" accept={c.accept} onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              {file ? (
                <span>
                  <strong>{file.name}</strong> · {(file.size / 1024).toFixed(1)} kB
                </span>
              ) : (
                <span>Drop a file or click to choose</span>
              )}
            </label>
            <ol className="import__steps">
              <li>Detect format</li>
              <li>Preview mapped, unmapped and conflicting fields</li>
              <li>Record provenance (SHA-256, adapter version)</li>
              <li>Commit as a new revision</li>
            </ol>
            <div className="row">
              <Button tone="primary" disabled>
                Detect and preview
              </Button>
              <NotWired id="importFile" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}


export function DeleteDialog() {
  const { state, dispatch, toast } = useStore();
  const [id, setId] = useState<string | null>(null);
  useEffect(() => {
    const h = (e: Event) => setId((e as CustomEvent<string>).detail);
    window.addEventListener("rawibumi:delete-request", h);
    return () => window.removeEventListener("rawibumi:delete-request", h);
  }, []);
  const e = state.entities.find((x) => x.id === id);
  if (!id || !e) return null;
  const close = () => setId(null);
  const doDelete = () => {
    if (e.source === "draft") {
      dispatch({ type: "deleteEntity", id: e.id });
      toast("info", `${e.name} deleted.`);
    } else toast("pending", `Deleting engine entities needs DELETE /scene/entities/{id} (not wired). ${e.name} is unchanged.`);
    close();
  };
  return (
    <div className="modal-backdrop" onClick={close}>
      <div className="modal modal--small" role="alertdialog" onClick={(ev) => ev.stopPropagation()}>
        <header className="modal__head">
          <h3>Delete {e.name}?</h3>
        </header>
        <div className="modal__body">
          {e.hostsPvField ? (
            <>
              <p>This surface hosts a PV field. Choose what happens to it; nothing is removed silently.</p>
              <div className="stack">
                <Button tone="danger" onClick={doDelete}>
                  Delete surface and its PV field
                </Button>
                <Button onClick={doDelete}>Detach the PV field, delete surface</Button>
                <Button tone="ghost" onClick={close}>
                  Cancel
                </Button>
              </div>
            </>
          ) : (
            <>
              <p>{e.source === "draft" ? "This local draft will be removed. Undo restores it." : "The engine entity will be removed as a new revision."}</p>
              <div className="row">
                <Button tone="danger" onClick={doDelete}>
                  Delete
                </Button>
                <Button tone="ghost" onClick={close}>
                  Cancel
                </Button>
              </div>
            </>
          )}
          {e.source === "engine" && (
            <p className="sub">
              Engine delete <NotWired id="deleteEntity" compact />
            </p>
          )}
        </div>
      </div>
    </div>
  );
}


export function Toasts() {
  const { state, dispatch } = useStore();
  useEffect(() => {
    if (!state.toasts.length) return;
    const t = setTimeout(() => dispatch({ type: "dismissToast", id: state.toasts[0].id }), 6000);
    return () => clearTimeout(t);
  }, [state.toasts, dispatch]);
  return (
    <div className="toasts" aria-live="polite">
      {state.toasts.map((t) => (
        <div key={t.id} className={`toast toast--${t.tone}`}>
          <span>{t.text}</span>
          <button type="button" className="iconbtn" onClick={() => dispatch({ type: "dismissToast", id: t.id })} aria-label="Dismiss">
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}