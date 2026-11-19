import { useEffect, useRef, useState } from "react";
import { token } from "./ui/palette";
import { useTranslation } from "react-i18next";
import { GeoJSONSource, Map, Marker, NavigationControl, setWorkerUrl, type StyleSpecification } from "maplibre-gl";
import { openProviderSettings, useImageryProvider } from "./imagery/ProviderDialog";
import type { ImageryProvider } from "./imagery/provider";
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";


import type { SceneView } from "./types";


setWorkerUrl(workerUrl);


const DEFAULT_STYLE = import.meta.env.VITE_MAP_STYLE_URL || "https://tiles.openfreemap.org/styles/liberty";


interface MapWorkspaceProps {
  site: SceneView["site"];
  geojson: SceneView["geojson"];
  onCoordinatePick?: (latitude: number, longitude: number) => void;
  compact?: boolean;
  /** UX1: offer the Streets / Satellite / Hybrid switch. */
  basemaps?: boolean;
  /** UX1: change to zoom to the site at street level (the landing "Zoom to point"). */
  zoomRequest?: number;
}

export type Basemap = "streets" | "satellite" | "hybrid";

/** The provider's raster as a MapLibre source: the key is filled in here, in the browser, and nowhere else. */
function rasterSource(provider: ImageryProvider, key: string) {
  return { type: "raster" as const, tiles: [provider.tileUrlTemplate.replace("{key}", encodeURIComponent(key))], tileSize: 256, attribution: provider.attribution, maxzoom: 22 };
}

function satelliteStyle(provider: ImageryProvider, key: string): StyleSpecification {
  return { version: 8, sources: { "rawibumi-imagery": rasterSource(provider, key) }, layers: [{ id: "rawibumi-imagery", type: "raster", source: "rawibumi-imagery" }] };
}

/** Hybrid: the provider's raster under the street style's labels. */
function addHybridRaster(map: Map, provider: ImageryProvider, key: string) {
  if (map.getSource("rawibumi-imagery")) return;
  map.addSource("rawibumi-imagery", rasterSource(provider, key));
  const firstLabel = map.getStyle().layers.find((layer) => layer.type === "symbol")?.id;
  map.addLayer({ id: "rawibumi-imagery", type: "raster", source: "rawibumi-imagery" }, firstLabel);
}


function installEngineeringLayers(map: Map, geojson: SceneView["geojson"]) {
  if (!map.getSource("rawibumi-scene")) {
    map.addSource("rawibumi-scene", { type: "geojson", data: geojson as never });
  }
  if (!map.getLayer("rawibumi-surfaces")) {
    map.addLayer({ id: "rawibumi-surfaces", type: "fill", source: "rawibumi-scene", filter: ["==", ["get", "category"], "surface"], paint: { "fill-color": token("color-tse-700"), "fill-opacity": 0.22, "fill-outline-color": token("color-tse-700") } });
  }
  if (!map.getLayer("rawibumi-obstacles")) {
    map.addLayer({ id: "rawibumi-obstacles", type: "fill", source: "rawibumi-scene", filter: ["==", ["get", "category"], "obstacle"], paint: { "fill-color": token("role-error-glyph"), "fill-opacity": 0.4, "fill-outline-color": token("role-error-text") } });
  }
  if (!map.getLayer("rawibumi-modules")) {
    map.addLayer({ id: "rawibumi-modules", type: "fill", source: "rawibumi-scene", filter: ["==", ["get", "category"], "module"], paint: { "fill-color": token("color-mppt-paper-2"), "fill-opacity": 0.74, "fill-outline-color": token("color-ink-900") } });
  }
  if (!map.getLayer("rawibumi-scene-outline")) {
    map.addLayer({ id: "rawibumi-scene-outline", type: "line", source: "rawibumi-scene", paint: { "line-color": token("color-ink-900"), "line-width": 1.1, "line-opacity": 0.72 } });
  }
}


export function validMapCoordinates(latitude: number, longitude: number): boolean {
  return Number.isFinite(latitude) && Math.abs(latitude) < 90 && Number.isFinite(longitude) && Math.abs(longitude) <= 180;
}

export function MapWorkspace({ site, geojson, onCoordinatePick, compact = false, basemaps = false, zoomRequest }: MapWorkspaceProps) {
  const { t } = useTranslation();
  const lastValid = useRef({ latitude_deg: 0, longitude_deg: 0 });
  if (validMapCoordinates(site.latitude_deg, site.longitude_deg)) lastValid.current = site;
  const centre = lastValid.current;
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<Map | null>(null);
  const markerRef = useRef<Marker | null>(null);
  const pickRef = useRef(onCoordinatePick);
  const geojsonRef = useRef(geojson);
  const [mapContextError, setMapContextError] = useState<string | null>(null);
  pickRef.current = onCoordinatePick;
  geojsonRef.current = geojson;
  // UX1 basemap switch; declared after the existing refs so their order is unchanged.
  const imagery = useImageryProvider();
  const [basemapChoice, setBasemap] = useState<Basemap>("streets");
  const basemap = basemapChoice ?? "streets";
  const basemapRef = useRef<Basemap>("streets");
  const imageryRef = useRef(imagery);
  imageryRef.current = imagery;


  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    let map: Map;
    try {
      map = new Map({ container: containerRef.current, style: DEFAULT_STYLE, center: [centre.longitude_deg, centre.latitude_deg], zoom: compact ? 3.5 : 19, pitch: 0, bearing: 0 });
    } catch (error) {
      setMapContextError(error instanceof Error ? error.message : String(error));
      return;
    }
    map.addControl(new NavigationControl({ showCompass: true }), "top-right");
    markerRef.current = new Marker({ color: token("color-ink-900") }).setLngLat([centre.longitude_deg, centre.latitude_deg]).addTo(map);
    // Every style (re)load: the engineering layers, and in Hybrid the provider's raster under the labels.
    map.on("style.load", () => {
      setMapContextError(null);
      const { provider, key, ready } = imageryRef.current;
      if (basemapRef.current === "hybrid" && ready && provider) addHybridRaster(map, provider, key);
      installEngineeringLayers(map, geojsonRef.current);
    });
    map.on("error", (event) => {
      const detail = event.error instanceof Error ? event.error.message : "The contextual map style or tiles could not be loaded.";
      setMapContextError(detail);
    });
    map.on("click", (event) => {
      if (!pickRef.current) return;
      markerRef.current?.setLngLat(event.lngLat);
      pickRef.current(event.lngLat.lat, event.lngLat.lng);
    });
    mapRef.current = map;
    return () => {
      markerRef.current?.remove();
      markerRef.current = null;
      map.remove();
      mapRef.current = null;
    };
  }, [compact]);


  useEffect(() => {
    const map = mapRef.current;
    if (!map || !validMapCoordinates(site.latitude_deg, site.longitude_deg)) return;
    markerRef.current?.setLngLat([centre.longitude_deg, centre.latitude_deg]);
    map.setCenter([centre.longitude_deg, centre.latitude_deg]);
  }, [compact, site.latitude_deg, site.longitude_deg]);


  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    const source = map.getSource("rawibumi-scene") as GeoJSONSource | undefined;
    source?.setData(geojson as never);
  }, [geojson]);

  // A provider removed or made unusable elsewhere falls back to Streets.
  const shown: Basemap = imagery.ready ? basemap : "streets";
  useEffect(() => {
    const map = mapRef.current;
    if (!map || basemapRef.current === shown) return;
    basemapRef.current = shown;
    const { provider, key } = imageryRef.current;
    map.setStyle(shown === "satellite" && provider ? satelliteStyle(provider, key) : DEFAULT_STYLE);
  }, [shown, imagery.provider?.tileUrlTemplate, imagery.key]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || zoomRequest === undefined || !validMapCoordinates(site.latitude_deg, site.longitude_deg)) return;
    map.flyTo({ center: [site.longitude_deg, site.latitude_deg], zoom: 18 });
  }, [zoomRequest]);


  return (
    <div className={compact ? "map-frame map-frame--compact" : "map-frame"}>
      <div ref={containerRef} className={compact ? "map-canvas map-canvas--compact" : "map-canvas"} aria-label={t("hardening.mapLabel")} />
      {basemaps && (
        <div className="map-basemaps" role="group" aria-label={t("imagery.basemap")} data-basemap={shown}>
          {(["streets", "satellite", "hybrid"] as const).map((b) => (
            <button key={b} type="button" className={shown === b ? "segmented__opt segmented__opt--on" : "segmented__opt"} aria-pressed={shown === b}
              disabled={b !== "streets" && !imagery.ready} title={b !== "streets" && !imagery.ready ? t("imagery.noProvider") : undefined}
              onClick={() => setBasemap(b)}>{t(`imagery.basemap_${b}`)}</button>
          ))}
          {!imagery.ready && <button type="button" className="btn btn--sm" onClick={openProviderSettings}>{t("imagery.setUp")}</button>}
        </div>
      )}
      {mapContextError && (
        <div className="map-context-warning" role="status">
          <strong>{t("hardening.mapUnavailable")}</strong>
          <span>{t("hardening.mapHint")}</span>
        </div>
      )}
    </div>
  );
}
