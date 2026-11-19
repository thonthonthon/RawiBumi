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
  fillPreview: {
    id: "fillPreview",
    method: "POST",
    path: "/api/projects/{id}/pv-fields/fill-preview",
    purpose: "Table-level fill preview: module count in both orientations, usable region and re-fill diff (proposal 0003)",
    specRef: "Plan B5; proposal 0003 (E2, E3, E4)"
  },
  fillApply: {
    id: "fillApply",
    method: "POST",
    path: "/api/projects/{id}/pv-fields/fill",
    purpose: "Apply a table-level fill or re-fill, keeping pinned tables, as one undo step (proposal 0003)",
    specRef: "Plan B5; proposal 0003 (E2, E3, E6)"
  },
  tableEdit: {
    id: "tableEdit",
    method: "POST",
    path: "/api/projects/{id}/pv-fields/{pv_field_id}/tables/commands",
    purpose: "Move, delete or unpin tables and delete modules; each edit pins what it touches (proposal 0003)",
    specRef: "Plan B5; proposal 0003 (E3, E6)"
  },
  moduleEdit: {
    id: "moduleEdit",
    method: "POST",
    path: "/api/projects/{id}/modules/edit",
    purpose: "Add or rotate individual modules",
    specRef: "UI spec §6.6"
  },
  importFile: {
    id: "importFile",
    method: "POST",
    path: "/api/projects/{id}/imports",
    purpose: "Import hub: COLLADA/SHD, horizon, load",
    specRef: "UI spec §6.1, §6.5"
  },
  subHourlyTimestep: {
    id: "subHourlyTimestep", method: "POST", path: "/api/projects/{id}/simulate",
    purpose: "Sub-hourly simulation timesteps", specRef: "S7d D8"
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
