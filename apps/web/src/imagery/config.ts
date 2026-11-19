import type { OpenSIMPVMapLayerConfigurationV01 as MapLayerConfiguration } from "../generated/schemas/map-layer-configuration";
import { CREDENTIAL_REFERENCE, type ImageryProvider } from "./provider";
import { fromControlPoints, toControlPoints, type OverlayTransform } from "./transform";

export type { MapLayerConfiguration };

/** The project's imagery as the editor sees it; the persisted form is a MapLayerConfiguration (UX1 D1). */
export interface ProjectImagery {
  satellite: { name: string; template: string; attribution: string; credentialReference: string; opacity: number } | null;
  overlay: { assetId: string; name: string; width: number; height: number; transform: OverlayTransform; opacity: number; locked: boolean } | null;
}

const OPACITY = 0.85;

export function parseImagery(config: MapLayerConfiguration | null | undefined): ProjectImagery {
  const out: ProjectImagery = { satellite: null, overlay: null };
  if (!config) return out;
  const providers = new Map(config.providers.map((p) => [p.provider_id, p]));
  for (const layer of config.layers) {
    const provider = layer.provider_id ? providers.get(layer.provider_id) : undefined;
    if (layer.layer_type === "aerial_imagery" && provider?.tile_url_template)
      out.satellite = { name: provider.name, template: provider.tile_url_template, attribution: provider.attribution ?? "",
        credentialReference: provider.credential_reference ?? CREDENTIAL_REFERENCE, opacity: layer.opacity ?? OPACITY };
    const reference = layer.orthophoto_georeference;
    if (layer.layer_type === "orthophoto" && layer.imported_asset_id && reference)
      out.overlay = { assetId: layer.imported_asset_id, name: provider?.name ?? "Overlay", width: reference.image_width_px, height: reference.image_height_px,
        transform: fromControlPoints(reference.control_points).transform, opacity: layer.opacity ?? OPACITY, locked: layer.locked ?? false };
  }
  return out;
}

/** The persisted MapLayerConfiguration, or null when nothing is configured. The key is never part of it. */
export function imageryConfig(imagery: ProjectImagery): MapLayerConfiguration | null {
  if (!imagery.satellite && !imagery.overlay) return null;
  const config: MapLayerConfiguration = {
    schema_name: "MapLayerConfiguration", schema_version: "0.1", map_configuration_id: "project-imagery",
    engineering_geometry_authority: "local_metric", map_measurement_role: "context_only", providers: [], layers: []
  };
  const s = imagery.satellite;
  if (s) {
    config.providers.push({ provider_id: "custom-imagery", provider_kind: "xyz_raster", name: s.name, tile_url_template: s.template,
      credential_reference: s.credentialReference, attribution_required: true, attribution: s.attribution || s.name });
    config.layers.push({ layer_id: "satellite", layer_type: "aerial_imagery", provider_id: "custom-imagery", opacity: s.opacity });
  }
  const o = imagery.overlay;
  if (o) {
    config.providers.push({ provider_id: "overlay", provider_kind: "uploaded_asset", name: o.name, attribution_required: false });
    config.layers.push({ layer_id: "overlay", layer_type: "orthophoto", provider_id: "overlay", imported_asset_id: o.assetId,
      opacity: o.opacity, locked: o.locked,
      orthophoto_georeference: { method: "affine_control_points", image_width_px: o.width, image_height_px: o.height,
        control_points: toControlPoints(o.transform, o.width, o.height), rms_error_m: 0 } });
  }
  return config;
}

export function satelliteFrom(provider: ImageryProvider, opacity = OPACITY): NonNullable<ProjectImagery["satellite"]> {
  return { name: provider.name, template: provider.tileUrlTemplate, attribution: provider.attribution, credentialReference: CREDENTIAL_REFERENCE, opacity };
}

/** A first placement: the image centred on the plan origin at 0.05 m/px, square pixels, no rotation. */
export function initialOverlay(asset: { asset_id: string; filename: string; width_px: number; height_px: number }): NonNullable<ProjectImagery["overlay"]> {
  const m = 0.05;
  return { assetId: asset.asset_id, name: asset.filename, width: asset.width_px, height: asset.height_px, opacity: OPACITY, locked: false,
    transform: { offset: [-(asset.width_px * m) / 2, (asset.height_px * m) / 2], rotationDeg: 0, sx: m, sy: m } };
}
