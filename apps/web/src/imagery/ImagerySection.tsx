import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { engine } from "../client";
import { useActions } from "../state/store";
import { Button, Check, Field, Section } from "../ui/kit";
import { initialOverlay, satelliteFrom, type ProjectImagery } from "./config";
import { imageHeader } from "./header";
import { openProviderSettings, useImageryProvider } from "./ProviderDialog";
import { useImagery } from "./useImagery";

/** A number committed on Enter or blur only, so typing never creates an undo step per keystroke. */
function CommitNumber({ value, onCommit, step = 0.01, min, disabled, label }: { value: number; onCommit: (v: number) => void; step?: number; min?: number; disabled?: boolean; label: string }) {
  const shown = String(Math.round(value * 1e6) / 1e6);
  const [text, setText] = useState(shown);
  useEffect(() => setText(shown), [shown]);
  const commit = () => {
    const v = Number(text);
    // Compare at the shown precision: a saved value read back from control points carries float noise.
    if (text.trim() !== "" && Number.isFinite(v) && (min === undefined || v >= min) && v !== Number(shown)) onCommit(v);
    else setText(shown);
  };
  return <input className="input input--num" type="number" aria-label={label} step={step} min={min} disabled={disabled} value={text}
    onChange={(e) => setText(e.target.value)} onBlur={commit} onKeyDown={(e) => { if (e.key === "Enter") commit(); if (e.key === "Escape") setText(shown); }} />;
}

/** Opacity while dragging the slider; saved once on release. */
function OpacitySlider({ value, onCommit, label }: { value: number; onCommit: (v: number) => void; label: string }) {
  const [live, setLive] = useState(value);
  const start = useRef(value);
  useEffect(() => { setLive(value); start.current = value; }, [value]);
  const commit = () => { if (live !== start.current) onCommit(live); };
  return <input type="range" aria-label={label} min={0.1} max={1} step={0.05} value={live} onChange={(e) => setLive(Number(e.target.value))}
    onPointerUp={commit} onKeyUp={commit} onBlur={commit} />;
}

/** Site panel imagery (UX1): the custom-provider satellite underlay and the persisted, calibrated image overlay. */
export function ImagerySection() {
  const { t } = useTranslation();
  const { toast, run } = useActions();
  const { imagery, save, projectId } = useImagery();
  const provider = useImageryProvider();
  const [fileError, setFileError] = useState<string | null>(null);
  const edit = (next: Partial<ProjectImagery>) => save({ ...imagery, ...next });
  const o = imagery.overlay;
  const setOverlay = (patch: Partial<NonNullable<ProjectImagery["overlay"]>>) => o && edit({ overlay: { ...o, ...patch } });
  const setTransform = (patch: Partial<NonNullable<ProjectImagery["overlay"]>["transform"]>) => o && setOverlay({ transform: { ...o.transform, ...patch } });

  async function upload(file: File) {
    setFileError(null);
    const header = imageHeader(new Uint8Array(await file.slice(0, 65536).arrayBuffer()));
    if ("problem" in header) return setFileError(t(header.problem));
    if (file.size > 10 * 1000 * 1000) return setFileError(t("imagery.tooLarge"));
    if (!projectId) return;
    const asset = await run(t("imagery.uploading"), () => engine.uploadImageryAsset(projectId, file, file.name));
    if (asset) await edit({ overlay: initialOverlay(asset) });
  }

  return (
    <Section title={t("sections.background")}>
      <p className="note">{t("imagery.contextOnly")}</p>
      <div className="stack" data-imagery-satellite={imagery.satellite ? "on" : "off"}>
        <Check
          checked={!!imagery.satellite}
          disabled={!imagery.satellite && !provider.ready}
          label={t("imagery.satellite")}
          onChange={(on) => void edit({ satellite: on && provider.provider ? satelliteFrom(provider.provider) : null })}
        />
        {!provider.ready && <p className="note">{t("imagery.noProvider")} <Button small onClick={openProviderSettings}>{t("imagery.setUp")}</Button></p>}
        {imagery.satellite && !provider.key && imagery.satellite.template.includes("{key}") && <p className="issue issue--draft" role="status">{t("imagery.keyMissing")}</p>}
        {imagery.satellite && <Field label={t("imagery.opacity")}><OpacitySlider label={t("imagery.opacity")} value={imagery.satellite.opacity} onCommit={(opacity) => void edit({ satellite: { ...imagery.satellite!, opacity } })} /></Field>}
        {provider.provider && <Button small onClick={openProviderSettings}>{t("imagery.providerSettings")}</Button>}
      </div>
      <div className="stack" data-imagery-overlay={o ? (o.locked ? "locked" : "unlocked") : "none"}>
        <Field label={o ? t("imagery.replaceImage") : t("imagery.uploadImage")} hint={t("imagery.uploadHint")}>
          <input className="input" type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void upload(f).catch((err) => toast("error", err instanceof Error ? err.message : String(err))); }} />
        </Field>
        {fileError && <p className="form-error" role="alert">{fileError}</p>}
        {o && (
          <>
            <p className="sub">{o.name} · {o.width} × {o.height} px</p>
            <div className="grid2">
              <Field label={t("imagery.mppAcross")} unit="m/px"><CommitNumber label={t("imagery.mppAcross")} step={0.001} min={0.0001} disabled={o.locked} value={o.transform.sx} onCommit={(sx) => setTransform({ sx, sy: o.transform.sx === o.transform.sy ? sx : o.transform.sy })} /></Field>
              <Field label={t("imagery.mppDown")} unit="m/px"><CommitNumber label={t("imagery.mppDown")} step={0.001} min={0.0001} disabled={o.locked} value={o.transform.sy} onCommit={(sy) => setTransform({ sy })} /></Field>
              <Field label={t("imagery.rotation")} unit="° ccw"><CommitNumber label={t("imagery.rotation")} step={0.1} disabled={o.locked} value={o.transform.rotationDeg} onCommit={(rotationDeg) => setTransform({ rotationDeg })} /></Field>
              <Field label={t("imagery.topLeftX")} unit="m"><CommitNumber label={t("imagery.topLeftX")} disabled={o.locked} value={o.transform.offset[0]} onCommit={(x) => setTransform({ offset: [x, o.transform.offset[1]] })} /></Field>
              <Field label={t("imagery.topLeftY")} unit="m"><CommitNumber label={t("imagery.topLeftY")} disabled={o.locked} value={o.transform.offset[1]} onCommit={(y) => setTransform({ offset: [o.transform.offset[0], y] })} /></Field>
            </div>
            <p className="note">{t(o.locked ? "imagery.lockedNote" : "imagery.adjustNote")}</p>
            <div className="row">
              <Button small disabled={o.locked} onClick={() => window.dispatchEvent(new Event("rawibumi:overlay-calibrate"))}>{t("imagery.calibrate")}</Button>
              <Button small onClick={() => void setOverlay({ locked: !o.locked })}>{t(o.locked ? "imagery.unlock" : "imagery.lock")}</Button>
              <Button small tone="danger" onClick={() => void edit({ overlay: null })}>{t("imagery.removeImage")}</Button>
            </div>
            <Field label={t("imagery.opacity")}><OpacitySlider label={t("imagery.overlayOpacity")} value={o.opacity} onCommit={(opacity) => void setOverlay({ opacity })} /></Field>
          </>
        )}
      </div>
    </Section>
  );
}
