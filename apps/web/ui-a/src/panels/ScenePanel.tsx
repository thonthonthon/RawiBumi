import { Tool, useStore } from "../state/store";
import { area } from "../geometry";
import { Button, Check, NotWired, Section } from "../ui/kit";
import { Eye, EyeOff, Lock, Unlock } from "../ui/icons";


const TOOLS: Array<{ tool: Tool; label: string; key: string; wired: boolean; note: string }> = [
  { tool: "select", label: "Select / move", key: "V", wired: true, note: "Drag to move, handles for vertices and rotation" },
  { tool: "rect_engine", label: "Rectangle surface", key: "R", wired: true, note: "Created directly in the engine" },
  { tool: "polygon", label: "Free polygon surface", key: "P", wired: false, note: "Concave allowed, any vertex count" },
  { tool: "hole", label: "Hole in surface", key: "H", wired: false, note: "Skylights, courtyards, cut-outs" },
  { tool: "obstacle", label: "Polygon obstacle", key: "O", wired: false, note: "Extruded to a height" },
  { tool: "keepout", label: "Keep-out zone", key: "K", wired: false, note: "Fire access, walkways, no-PV areas" },
  { tool: "measure", label: "Measure", key: "M", wired: true, note: "Distance and bearing from north" }
];


export function ScenePanel({ onImport }: { onImport: () => void }) {
  const { state, dispatch } = useStore();
  const kinds: Array<["surface" | "obstacle" | "keepout", string]> = [
    ["surface", "Surfaces"],
    ["obstacle", "Obstacles"],
    ["keepout", "Keep-out zones"]
  ];
  return (
    <>
      <Section title="Tools">
        <div className="toollist">
          {TOOLS.map((t) => (
            <button
              key={t.tool}
              type="button"
              className={state.tool === t.tool ? "tool tool--on" : "tool"}
              onClick={() => dispatch({ type: "setTool", tool: t.tool })}
              title={t.note}
            >
              <kbd>{t.key}</kbd>
              <span className="tool__label">{t.label}</span>
              {!t.wired && <NotWired id={t.tool === "obstacle" ? "polygonObstacle" : t.tool === "keepout" ? "keepout" : t.tool === "hole" ? "editVertices" : "polygonSurface"} compact />}
            </button>
          ))}
        </div>
        <p className="note">
          Double-click an edge to insert a vertex, Alt-click a vertex to delete it, Delete removes the selection. Unwired edits stay as dashed local drafts
          and are listed in Findings.
        </p>
        <div className="row">
          <Button small onClick={onImport}>
            Import geometry…
          </Button>
          <Button small tone="ghost" onClick={() => window.dispatchEvent(new Event("rawibumi:fit"))}>
            Fit view (F)
          </Button>
        </div>
      </Section>


      <Section title="Snapping">
        <div className="checks">
          <Check checked={state.snap.vertex} onChange={(vertex) => dispatch({ type: "setSnap", patch: { vertex } })} label="Vertices" />
          <Check checked={state.snap.angle} onChange={(angle) => dispatch({ type: "setSnap", patch: { angle } })} label="15° with Shift" />
          <Check checked={state.snap.grid} onChange={(grid) => dispatch({ type: "setSnap", patch: { grid } })} label={`Grid ${state.snap.gridStep} m`} />
        </div>
      </Section>


      <Section title="Layers">
        {kinds.map(([k, label]) => {
          const list = state.entities.filter((e) => e.kind === k);
          return (
            <div className="layer-group" key={k}>
              <div className="layer-group__head">
                {label} <span className="count">{list.length}</span>
              </div>
              {list.length === 0 && <div className="empty">None yet</div>}
              {list.map((e) => (
                <div
                  key={e.id}
                  className={state.selection.includes(e.id) ? "layer layer--on" : "layer"}
                  onClick={() => dispatch({ type: "select", ids: [e.id] })}
                  onMouseEnter={() => dispatch({ type: "hover", id: e.id })}
                  onMouseLeave={() => dispatch({ type: "hover", id: null })}
                >
                  <span className={`swatch swatch--${e.kind}${e.source === "draft" ? " swatch--draft" : ""}`} />
                  <span className="layer__name">{e.name}</span>
                  <span className="layer__meta">{area(e.polygon, e.holes).toFixed(1)} m²</span>
                  {e.source === "draft" && <span className="tag tag--draft">draft</span>}
                  {e.modified && <span className="tag tag--draft">edited</span>}
                  <button
                    type="button"
                    className="iconbtn"
                    title={e.hidden ? "Show" : "Hide"}
                    onClick={(ev) => {
                      ev.stopPropagation();
                      dispatch({ type: "updateEntity", id: e.id, patch: { hidden: !e.hidden }, history: false });
                    }}
                  >
                    {e.hidden ? <EyeOff /> : <Eye />}
                  </button>
                  <button
                    type="button"
                    className="iconbtn"
                    title={e.locked ? "Unlock" : "Lock"}
                    onClick={(ev) => {
                      ev.stopPropagation();
                      dispatch({ type: "updateEntity", id: e.id, patch: { locked: !e.locked }, history: false });
                    }}
                  >
                    {e.locked ? <Lock /> : <Unlock />}
                  </button>
                </div>
              ))}
            </div>
          );
        })}
      </Section>
    </>
  );
}