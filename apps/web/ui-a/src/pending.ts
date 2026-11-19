/**
 * Registry of UI features whose engine/API side is not wired yet.
 * Every "Not wired" badge in the UI points at one of these ids, so Codex/backend work
 * can grep for the id and implement the matching endpoint.
 */
export interface PendingEndpoint {
  id: string;
  method: "GET" | "POST" | "PATCH" | "DELETE";
  path: string;
  purpose: string;
  specRef: string;
}

export const PENDING: Record<string, PendingEndpoint> = {
  polygonSurface: {
    id: "polygonSurface",
    method: "POST",
    path: "/api/projects/{id}/surfaces/polygon",
    purpose: "Create a free-shape surface with holes and a plane definition",
    specRef: "UI spec §6.3, §6.4"
  },
  polygonObstacle: {
    id: "polygonObstacle",
    method: "POST",
    path: "/api/projects/{id}/obstacles/extrusion",
    purpose: "Create a polygon-extrusion obstacle",
    specRef: "Scene spec §29; UI spec §6.3"
  },
  keepout: {
    id: "keepout",
    method: "POST",
    path: "/api/projects/{id}/exclusions",
    purpose: "Create an exclusion zone / walkway",
    specRef: "Scene spec §31–32"
  },
  editVertices: {
    id: "editVertices",
    method: "POST",
    path: "/api/projects/{id}/scene/vertices",
    purpose: "Vertex insert/move/delete on an existing entity (engine 4.7H-B exists; HTTP route missing)",
    specRef: "UI spec §6.3"
  },
  rotateEntity: {
    id: "rotateEntity",
    method: "POST",
    path: "/api/projects/{id}/scene/rotate",
    purpose: "Rotate entity about pivot (engine 4.2 exists; HTTP route missing)",
    specRef: "UI spec §6.3"
  },
  scaleEntity: {
    id: "scaleEntity",
    method: "POST",
    path: "/api/projects/{id}/scene/resize",
    purpose: "Resize surface/obstacle/zone (never modules)",
    specRef: "UI spec §6.3"
  },
  deleteEntity: {
    id: "deleteEntity",
    method: "DELETE",
    path: "/api/projects/{id}/scene/entities/{entity_id}",
    purpose: "Fail-closed delete with dependent-field policy",
    specRef: "UI spec §6.3"
  },
  planeDefinition: {
    id: "planeDefinition",
    method: "PATCH",
    path: "/api/projects/{id}/surfaces/{surface_id}/plane",
    purpose: "Set plane definition; engine derives Z with provenance",
    specRef: "UI spec §6.4"
  },
  undoRedo: {
    id: "undoRedo",
    method: "POST",
    path: "/api/projects/{id}/scene/undo | /redo",
    purpose: "Engine-side atomic undo/redo (UI keeps a local draft history meanwhile)",
    specRef: "Scene spec §23"
  },
  moduleEdit: {
    id: "moduleEdit",
    method: "POST",
    path: "/api/projects/{id}/modules/edit",
    purpose: "Add/delete/move/rotate individual modules and tables",
    specRef: "UI spec §6.6"
  },
  importFile: {
    id: "importFile",
    method: "POST",
    path: "/api/projects/{id}/imports",
    purpose: "Import hub: PAN/OND/templates, weather files, COLLADA/SHD, horizon, load",
    specRef: "UI spec §6.1, §6.5"
  },
  imageryConfig: {
    id: "imageryConfig",
    method: "PATCH",
    path: "/api/projects/{id}/imagery",
    purpose: "Persist imagery provider/upload registration and provenance",
    specRef: "UI spec §6.2"
  },
  siteEdit: {
    id: "siteEdit",
    method: "PATCH",
    path: "/api/projects/{id}/site",
    purpose: "Edit site coordinates/elevation/timezone after creation",
    specRef: "UI spec §1 defects"
  },
  tablePairing: {
    id: "tablePairing",
    method: "POST",
    path: "/api/projects/{id}/electrical/pairing",
    purpose: "Pair tables/PV fields to inverters",
    specRef: "UI spec §6.8.1"
  },
  notationApply: {
    id: "notationApply",
    method: "POST",
    path: "/api/projects/{id}/electrical/mppt-layout",
    purpose: "Apply per-inverter MPPT/input notation (e.g. 16,0;16,0;16,0;14,14)",
    specRef: "UI spec §6.8.2"
  },
  stringChecks: {
    id: "stringChecks",
    method: "POST",
    path: "/api/projects/{id}/electrical/check",
    purpose: "Voltage/current window checks per proposed string layout (engine 4.7 exists)",
    specRef: "UI spec §6.8.3"
  },
  orientationPolicy: {
    id: "orientationPolicy",
    method: "PATCH",
    path: "/api/projects/{id}/electrical/orientation-policy",
    purpose: "1° normal-angle tolerance and per-MPPT override with reason",
    specRef: "UI spec §6.8.5"
  },
  losses: {
    id: "losses",
    method: "PATCH",
    path: "/api/projects/{id}/losses",
    purpose: "Albedo, soiling, LID, mismatch, ohmic, availability, degradation",
    specRef: "UI spec §6.9.1"
  },
  loadProfile: {
    id: "loadProfile",
    method: "POST",
    path: "/api/projects/{id}/load",
    purpose: "Upload load profile with declared units, timestamp convention and timezone",
    specRef: "UI spec §6.9.2"
  },
  zeroExport: {
    id: "zeroExport",
    method: "PATCH",
    path: "/api/projects/{id}/zero-export",
    purpose: "Export-limit setpoint, measurement point, allocation policy",
    specRef: "UI spec §6.9.3"
  },
  timeSeries: {
    id: "timeSeries",
    method: "GET",
    path: "/api/projects/{id}/runs/{run_id}/timeseries",
    purpose: "Time series for heatmap, daily profiles and monthly meteo/PR/losses",
    specRef: "UI spec §7.1"
  },
  exportBundle: {
    id: "exportBundle",
    method: "POST",
    path: "/api/projects/{id}/runs/{run_id}/exports",
    purpose: "Server-side CSV/Parquet + JSON manifest bundle",
    specRef: "UI spec §7.3–7.4"
  },
  view3d: {
    id: "view3d",
    method: "GET",
    path: "/api/projects/{id}/scene/height-model",
    purpose: "Phase 4.4 height model for the 3D view",
    specRef: "UI spec §5.2"
  }
};

export class NotWiredError extends Error {
  constructor(public readonly endpointId: string) {
    const e = PENDING[endpointId];
    super(
      e
        ? `Not wired yet: ${e.method} ${e.path} — ${e.purpose}.`
        : `Not wired yet: ${endpointId}.`
    );
    this.name = "NotWiredError";
  }
}

export function notWired(endpointId: string): never {
  throw new NotWiredError(endpointId);
}
