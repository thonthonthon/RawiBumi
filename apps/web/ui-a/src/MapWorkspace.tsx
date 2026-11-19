import { useEffect, useRef, useState } from "react";
import { GeoJSONSource, Map, Marker, NavigationControl, setWorkerUrl } from "maplibre-gl";
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
}


function installEngineeringLayers(map: Map, geojson: SceneView["geojson"]) {
  if (!map.getSource("rawibumi-scene")) {
    map.addSource("rawibumi-scene", { type: "geojson", data: geojson as never });
  }
  if (!map.getLayer("rawibumi-surfaces")) {
    map.addLayer({ id: "rawibumi-surfaces", type: "fill", source: "rawibumi-scene", filter: ["==", ["get", "category"], "surface"], paint: { "fill-color": "#2563eb", "fill-opacity": 0.22, "fill-outline-color": "#1d4ed8" } });
  }
  if (!map.getLayer("rawibumi-obstacles")) {
    map.addLayer({ id: "rawibumi-obstacles", type: "fill", source: "rawibumi-scene", filter: ["==", ["get", "category"], "obstacle"], paint: { "fill-color": "#dc2626", "fill-opacity": 0.46, "fill-outline-color": "#991b1b" } });
  }
  if (!map.getLayer("rawibumi-modules")) {
    map.addLayer({ id: "rawibumi-modules", type: "fill", source: "rawibumi-scene", filter: ["==", ["get", "category"], "module"], paint: { "fill-color": "#0f766e", "fill-opacity": 0.74, "fill-outline-color": "#134e4a" } });
  }
  if (!map.getLayer("rawibumi-scene-outline")) {
    map.addLayer({ id: "rawibumi-scene-outline", type: "line", source: "rawibumi-scene", paint: { "line-color": "#111827", "line-width": 1.1, "line-opacity": 0.72 } });
  }
}


export function MapWorkspace({ site, geojson, onCoordinatePick, compact = false }: MapWorkspaceProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<Map | null>(null);
  const markerRef = useRef<Marker | null>(null);
  const pickRef = useRef(onCoordinatePick);
  const geojsonRef = useRef(geojson);
  const [mapContextError, setMapContextError] = useState<string | null>(null);
  pickRef.current = onCoordinatePick;
  geojsonRef.current = geojson;


  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = new Map({ container: containerRef.current, style: DEFAULT_STYLE, center: [site.longitude_deg, site.latitude_deg], zoom: compact ? 3.5 : 19, pitch: 0, bearing: 0 });
    map.addControl(new NavigationControl({ showCompass: true }), "top-right");
    markerRef.current = new Marker({ color: "#111827" }).setLngLat([site.longitude_deg, site.latitude_deg]).addTo(map);
    map.on("load", () => {
      setMapContextError(null);
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
    if (!map) return;
    markerRef.current?.setLngLat([site.longitude_deg, site.latitude_deg]);
    map.setCenter([site.longitude_deg, site.latitude_deg]);
  }, [compact, site.latitude_deg, site.longitude_deg]);


  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    const source = map.getSource("rawibumi-scene") as GeoJSONSource | undefined;
    source?.setData(geojson as never);
  }, [geojson]);


  return (
    <div className={compact ? "map-frame map-frame--compact" : "map-frame"}>
      <div ref={containerRef} className={compact ? "map-canvas map-canvas--compact" : "map-canvas"} aria-label="Map context for RawiBumi engineering scene" />
      {mapContextError && (
        <div className="map-context-warning" role="status">
          <strong>Map unavailable.</strong>
          <span>Type coordinates instead; engineering geometry stays usable on the blank plane.</span>
        </div>
      )}
    </div>
  );
}