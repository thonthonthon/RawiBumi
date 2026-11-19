import { engine } from "../client";
import type { ProjectView } from "../types";
import { parseImagery } from "./config";
import type { OverlayTransform } from "./transform";

/** The calibrated overlay as the report's plan figure draws it (UXF1, U2-15). */
export interface FigureOverlay {
  image: HTMLImageElement;
  width: number;
  height: number;
  transform: OverlayTransform;
  opacity: number;
}

// One decoded image per asset URL, shared by the plan canvas and the report figure.
const images = new Map<string, HTMLImageElement>();

export function overlayImage(src: string): HTMLImageElement {
  let image = images.get(src);
  if (!image) {
    image = new Image();
    image.src = src;
    images.set(src, image);
  }
  return image;
}

const loaded = (image: HTMLImageElement) => image.complete && image.naturalWidth > 0;

function overlayOf(view: ProjectView): { src: string; info: NonNullable<ReturnType<typeof parseImagery>["overlay"]> } | null {
  const info = parseImagery(view.bundle.imagery).overlay;
  const src = info ? engine.imageryAssetUrl(view.bundle.project.project_id, info.assetId) : "";
  return info && src ? { src, info } : null;
}

const figureOf = (image: HTMLImageElement, info: NonNullable<ReturnType<typeof overlayOf>>["info"]): FigureOverlay =>
  ({ image, width: info.width, height: info.height, transform: info.transform, opacity: info.opacity });

/** The project's overlay for the figure if its image is ready now; otherwise null (and the load starts). */
export function figureOverlay(view: ProjectView): FigureOverlay | null {
  const o = overlayOf(view);
  if (!o) return null;
  const image = overlayImage(o.src);
  return loaded(image) ? figureOf(image, o.info) : null;
}

/** Waits for the overlay image (at most `timeoutMs`); null when there is none or it does not load. */
export function figureOverlayLoaded(view: ProjectView, timeoutMs = 5000): Promise<FigureOverlay | null> {
  const o = overlayOf(view);
  if (!o) return Promise.resolve(null);
  const image = overlayImage(o.src);
  if (loaded(image)) return Promise.resolve(figureOf(image, o.info));
  return new Promise((resolve) => {
    const done = () => { window.clearTimeout(timer); resolve(loaded(image) ? figureOf(image, o.info) : null); };
    const timer = window.setTimeout(done, timeoutMs);
    image.addEventListener("load", done, { once: true });
    image.addEventListener("error", done, { once: true });
  });
}
