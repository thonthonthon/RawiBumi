import { useTranslation } from "react-i18next";
import { TOOLS } from "../canvas/tools";
import { SNAP_KINDS } from "../canvas/plan/snap";
import { area } from "../geometry";
import { useForm, useStore } from "../state/store";
import { Eye, EyeOff, Lock, Unlock } from "../ui/icons";
import { Button, Check, Field, NotWired, NumberInput, Section, Select } from "../ui/kit";

/** Inputs of the engine rectangle tools (B, O), shared with PlanCanvas through the form store. */
export interface SceneToolOptions {
  surfaceBaseM: number;
  obstacleBaseM: number;
  obstacleHeightM: number;
  keepoutType: "exclusion_area" | "walkway";
}
export const SCENE_TOOL_OPTIONS: SceneToolOptions = { surfaceBaseM: 0, obstacleBaseM: 0, obstacleHeightM: 1.5, keepoutType: "exclusion_area" };

export function ScenePanel({ onImport }: { onImport: () => void }) {
  const { t } = useTranslation();
  const { state, dispatch } = useStore();
  const [opts, setOpts] = useForm<SceneToolOptions>("scene.tools", SCENE_TOOL_OPTIONS);
  const kinds: Array<["surface" | "obstacle" | "keepout", string]> = [
    ["surface", "Surfaces"],
    ["obstacle", "Obstacles"],
    ["keepout", "Keep-out zones"]
  ];
  const snap = state.snap;
  const draftBlocksCommands = state.entities.some((e) => state.selection.includes(e.id) && e.source === "engine" && e.modified);
  return (
    <>
      <Section primary title={t("tools.title")}>
        <div className="toollist" role="toolbar" aria-label={t("tools.title")}>
          {TOOLS.map((d) => (
            <button
              key={d.tool}
              type="button"
              disabled={(!!state.busy && ["move", "rotate", "rect_engine", "polygon", "box_obstacle", "obstacle", "keepout"].includes(d.tool)) || (draftBlocksCommands && (d.tool === "move" || d.tool === "rotate"))}
              aria-pressed={state.tool === d.tool}
              className={state.tool === d.tool ? "tool tool--on" : "tool"}
              onClick={() => dispatch({ type: "setTool", tool: d.tool })}
              title={draftBlocksCommands && (d.tool === "move" || d.tool === "rotate") ? t("s7b.discardReason") : t(d.note)}
            >
              <kbd>{d.key.toUpperCase()}</kbd>
              <span className="tool__label">{t(d.label)}</span>
              {d.pending && <NotWired id={d.pending} compact />}
            </button>
          ))}
        </div>
        {state.tool === "keepout" && <Field label={t("s11a.keepoutType")}>
          <Select label={t("s11a.keepoutType")} value={opts.keepoutType ?? "exclusion_area"} onChange={(value) => setOpts({ ...opts, keepoutType: value as SceneToolOptions["keepoutType"] })}
            options={[{ value: "exclusion_area", label: t("s11a.exclusionZone") }, { value: "walkway", label: t("s11a.walkway") }]} />
        </Field>}
        {(state.tool === "rect_engine" || state.tool === "polygon") && (
          <div className="grid2">
            <Field label={t("tools.baseElevation")} unit="m">
              <NumberInput value={opts.surfaceBaseM} step={0.1} onChange={(surfaceBaseM) => setOpts({ ...opts, surfaceBaseM })} />
            </Field>
          </div>
        )}
        {(state.tool === "box_obstacle" || state.tool === "obstacle") && (
          <div className="grid2">
            <Field label={t("tools.baseElevation")} unit="m">
              <NumberInput value={opts.obstacleBaseM} step={0.1} onChange={(obstacleBaseM) => setOpts({ ...opts, obstacleBaseM })} />
            </Field>
            <Field label={t("tools.height")} unit="m">
              <NumberInput value={opts.obstacleHeightM} step={0.1} min={0} onChange={(obstacleHeightM) => setOpts({ ...opts, obstacleHeightM })} />
            </Field>
          </div>
        )}
        <p className="note">{t("tools.typedHelp")}</p>
        <p className="note">{t("tools.editHelp")}</p>
        <div className="row">
          <Button small onClick={onImport}>
            {t("tools.import")}
          </Button>
          <Button small tone="ghost" onClick={() => window.dispatchEvent(new Event("rawibumi:fit"))}>
            {t("tools.zoomAll")}
          </Button>
        </div>
      </Section>

      <Section primary title={t("sections.layers")}>
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

      <Section title={t("snap.title")}>
        <Check checked={snap.enabled} onChange={(enabled) => dispatch({ type: "setSnap", patch: { enabled } })} label={t("snap.enabled")} />
        <div className="checks">
          {SNAP_KINDS.map((k) => (
            <Check
              key={k}
              checked={snap[k] === true}
              disabled={!snap.enabled}
              onChange={(on) => dispatch({ type: "setSnap", patch: { [k]: on } })}
              label={t(`snap.${k}`)}
            />
          ))}
        </div>
        <div className="grid2">
          <Field label={t("snap.gridSpacing")} unit="m">
            <NumberInput value={snap.grid_spacing_m ?? 0.5} step={0.05} min={0.01} onChange={(grid_spacing_m) => dispatch({ type: "setSnap", patch: { grid_spacing_m } })} />
          </Field>
        </div>
        <Check checked={snap.angle15} onChange={(angle15) => dispatch({ type: "setSnap", patch: { angle15 } })} label={t("snap.angle15")} />
        <p className="note">{t("snap.help")}</p>
      </Section>


    </>
  );
}
