"""FastAPI surface for the Phase-6.0C browser product shell."""

from __future__ import annotations

import logging
import secrets
import threading
import time
import json
import math
import os
from pathlib import Path
from typing import Any, Callable, TypeVar, Literal, Annotated
from urllib.error import HTTPError

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, ConfigDict, StrictBool, StrictStr, StrictInt, field_validator, model_validator, StringConstraints
from jsonschema import Draft202012Validator, FormatChecker

from geometry.scene.bulk import GeometryBatchError, MAX_GEOMETRY_BYTES
from .project_store import FileProjectStore, ProjectCorruptError, ProjectNotFoundError
from .migrations import ProjectVersionError
from .history import HistoryConflictError
from .service import GeometryConflictError, ProjectConflictError, ProjectShellService, TopologyConsistencyError, DependentFieldError
from .study import BrowserStudyService, ProjectBusyError, simulation_defaults
from weather.providers import WeatherAcquisitionError
from reporting.exports.native_pdf import MAX_PDF_BYTES, NativePDFError


ROOT = Path(__file__).resolve().parents[2]
T = TypeVar("T")
logger = logging.getLogger(__name__)
_SCENE_COMMAND_SCHEMA = json.loads((ROOT / "apps/web/schema/scene-editor-command.schema.json").read_text())
_SCENE_COMMAND_VALIDATOR = Draft202012Validator(_SCENE_COMMAND_SCHEMA, format_checker=FormatChecker())
_ELECTRICAL_COMMAND_VALIDATOR = Draft202012Validator(
    json.loads((ROOT / "apps/web/schema/electrical-topology-command.schema.json").read_text()),
    format_checker=FormatChecker(),
)
_SURFACE_TYPES = tuple(json.loads((ROOT / "geometry/scene/scene.schema.json").read_text())["$defs"]["surface"]["properties"]["surface_type"]["enum"])


def _pdf_renderer_configured() -> bool:
    """Node, the web runtime and Chromium are named as absolute, existing paths (RAWIBUMI_PDF_*)."""
    paths = [os.environ.get(name) for name in ("RAWIBUMI_PDF_NODE", "RAWIBUMI_PDF_RUNTIME_ROOT", "RAWIBUMI_PDF_CHROMIUM_EXECUTABLE")]
    return all(value and Path(value).is_absolute() and Path(value).exists() for value in paths)


def _community_native_pdf_enabled() -> bool:
    """Deployment setting only; this is not requester authentication.

    DEC-P2 (user, 2026-11-08): on the community self-hosted edition the PDF is on whenever its renderer is configured;
    RAWIBUMI_COMMUNITY_NATIVE_PDF_ENABLED=0 turns it off and =1 turns it on explicitly. Any other flag value, and every
    other edition (hosted until Phase 8 login), stays off.
    """
    if os.environ.get("RAWIBUMI_DEPLOYMENT_EDITION") != "community_self_hosted":
        return False
    flag = os.environ.get("RAWIBUMI_COMMUNITY_NATIVE_PDF_ENABLED")
    if flag == "1":
        return True
    return flag is None and _pdf_renderer_configured()


class HistoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_project_revision_id: StrictStr = Field(min_length=1)
    expected_entry_id: StrictStr = Field(min_length=1)


class ElectricalExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requested_fidelity: Literal["level_2_bypass_substring"]
    fallback_policy: Literal["fail_closed", "explicit_lower_fidelity"] = "fail_closed"

class BrowserSimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    electrical_shading_configuration: ElectricalExecutionRequest | None = None


class UncertaintyAssumptionsRequest(BaseModel):
    """UNC1: the ledger is validated by the U1 kernel (codes and paths); null clears it."""
    model_config = ConfigDict(extra="forbid")
    ledger: dict[str, Any] | None


class NumericalCSVExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["csv"]
    resolution: Literal["hourly"]
    level: Literal["project"]
    columns: list[StrictStr] = Field(min_length=1, max_length=64)
    # S15: the hourly files' formats (default CSV only) and the full deliverable (monthly table, package documents,
    # run record). Without them the export is exactly the S7 CSV ZIP.
    formats: list[Literal["csv", "parquet"]] | None = Field(default=None, min_length=1, max_length=2)
    deliverable: StrictBool = False


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    latitude_deg: float = Field(ge=-90, le=90)
    longitude_deg: float = Field(ge=-180, le=180)
    timezone: str = Field(min_length=1, max_length=100)
    elevation_m: float | None = Field(default=None, ge=-500, le=9000)
    workspace_mode: str = "map_overlay"
    description: str | None = None


PatchName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]


class ProjectPatchRequest(BaseModel):
    distance_warning_m: float | None = Field(default=None, ge=0, le=10000, allow_inf_nan=False)
    model_config = ConfigDict(extra="forbid")
    name: PatchName | None = None
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("distance_warning_m")
    @classmethod
    def threshold_is_not_null(cls, value):
        if value is None:
            raise ValueError("distance_warning_m cannot be null")
        return value

    @field_validator("name")
    @classmethod
    def name_is_not_null(cls, value):
        if value is None:
            raise ValueError("name cannot be null")
        return value

    @model_validator(mode="after")
    def requires_change(self):
        if not self.model_fields_set:
            raise ValueError("project update requires name or description")
        return self


class SiteAddressDetails(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    text: str = Field(max_length=2000)
    source: Literal["lookup", "user"]
    attribution: str | None = Field(default=None, max_length=500)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    updatedAt: str = Field(max_length=64)


class SiteInstallationDetails(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    installationType: Literal["on_grid", "on_grid_zero_export", "off_grid", "hybrid"] | None = None
    bessEnergyKwh: float | None = Field(default=None, ge=0)
    bessPowerKw: float | None = Field(default=None, ge=0)


class SiteDetailsPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    address: SiteAddressDetails | None = None
    installation: SiteInstallationDetails | None = None
    copy_if_missing: bool = False

    @model_validator(mode="after")
    def requires_change(self):
        if not self.model_fields_set - {"copy_if_missing"}:
            raise ValueError("site details update requires address or installation")
        return self


class SitePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    name: PatchName | None = None
    latitude_deg: float | None = Field(default=None, ge=-90, le=90)
    longitude_deg: float | None = Field(default=None, ge=-180, le=180)
    elevation_m: float | None = Field(default=None, ge=-500, le=9000)
    timezone: str | None = Field(default=None, min_length=1, max_length=100)
    clear_weather_selection: bool = False

    @field_validator("name", "latitude_deg", "longitude_deg", "elevation_m", "timezone")
    @classmethod
    def site_value_is_not_null(cls, value):
        if value is None:
            raise ValueError("site values cannot be null")
        return value

    @model_validator(mode="after")
    def requires_change(self):
        if not self.model_fields_set - {"clear_weather_selection"}:
            raise ValueError("site update requires at least one site key")
        return self


def _finite_error_values(value):
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {k: _finite_error_values(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite_error_values(v) for v in value]
    return value


class WorkspaceModeRequest(BaseModel):
    mode: str


class SurfaceRectangleRequest(BaseModel):
    name: str = "Roof"
    origin_x_m: float = 0.0
    origin_y_m: float = 0.0
    width_m: float = Field(gt=0)
    height_m: float = Field(gt=0)
    base_elevation_m: float = 0.0
    surface_type: Literal[_SURFACE_TYPES] = "flat_roof"
    usable_for_pv: bool = True
    on_module_conflict: Literal["reject", "remove_modules", "refill_field"] = "reject"
    discard_dependent_strings: bool = False
    discard_manual_layout: bool = False
    dry_run: bool = False


class SceneMoveRequest(BaseModel):
    entity_id: str
    dx_m: float
    dy_m: float
    on_module_conflict: Literal["reject", "remove_modules", "refill_field"] = "reject"
    discard_dependent_strings: bool = False
    discard_manual_layout: bool = False
    dry_run: bool = False
    dependent_fields: Literal["reject", "apply"] = "reject"


class SceneCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: dict[str, Any]
    on_module_conflict: Literal["reject", "remove_modules", "refill_field"] = "reject"
    discard_dependent_strings: bool = False
    discard_manual_layout: bool = False
    dry_run: bool = False
    dependent_fields: Literal["reject", "apply"] = "reject"


class ElectricalCommandsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    commands: list[dict[str, Any]] = Field(min_length=1, max_length=200)
    dry_run: bool = False


ElectricalId = Annotated[StrictStr, Field(min_length=1)]


class ElectricalParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class CreateStringParameters(ElectricalParameters):
    take_from_unassigned: StrictBool = False
    module_instance_ids: list[ElectricalId] = Field(min_length=1, max_length=2000)
    string_id: Annotated[StrictStr, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")] | None = None
    name: str | None = None
    polarity: str = "normal"
    notes: str | None = None

    @field_validator("string_id")
    @classmethod
    def supplied_string_id_is_not_null(cls, value):
        if value is None:
            raise ValueError("string_id must be a non-empty string when supplied")
        return value


class StringIdsParameters(ElectricalParameters):
    string_ids: list[ElectricalId] = Field(min_length=1)


class AssignToMPPTParameters(StringIdsParameters):
    mppt_instance_id: ElectricalId
    enable: bool = True


class DeleteStringParameters(ElectricalParameters):
    string_id: ElectricalId


class CreateStringsParameters(ElectricalParameters):
    module_instance_ids: list[ElectricalId] = Field(min_length=1, max_length=20000)
    string_length: StrictInt = Field(ge=1)
    ordering: str = "row_major"
    remainder_policy: str = "error"
    id_prefix: Annotated[StrictStr, Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,15}$")] = "S"


class AssignStringsParameters(StringIdsParameters):
    inverter_instance_id: ElectricalId


class InverterIdParameters(ElectricalParameters):
    inverter_instance_id: ElectricalId


class SuggestStringLengthParameters(InverterIdParameters):
    module_definition_revision_id: ElectricalId
    mppt_index: StrictInt | None = Field(default=None, ge=1)


class SplitStringParameters(ElectricalParameters):
    string_id: ElectricalId
    after_module_instance_id: ElectricalId
    new_string_id: ElectricalId | None = None  # generated by the service when absent


class JoinStringsParameters(ElectricalParameters):
    first_string_id: ElectricalId
    second_string_id: ElectricalId


class MoveModuleParameters(ElectricalParameters):
    module_instance_id: ElectricalId
    to_string_id: ElectricalId | None = None
    index: StrictInt | None = Field(default=None, ge=0)


class SwapModulesParameters(ElectricalParameters):
    first_module_instance_id: ElectricalId
    second_module_instance_id: ElectricalId


class OrientationToleranceParameters(ElectricalParameters):
    # S14b: the user decided on 1°; a design may tighten it, not loosen it.
    tolerance_deg: float = Field(ge=0, le=1, allow_inf_nan=False, strict=True)


class OrientationOverrideParameters(ElectricalParameters):
    mppt_instance_id: ElectricalId
    reason: Annotated[StrictStr, Field(min_length=1, max_length=500)] | None


class InverterPairingParameters(ElectricalParameters):
    inverter_instance_id: ElectricalId
    pv_field_ids: list[ElectricalId] = Field(max_length=500)


class MpptLayoutParameters(ElectricalParameters):
    sources: list[Annotated[list[ElectricalId], Field(min_length=1, max_length=500)] | None] | None = Field(default=None, max_length=64)
    inverter_instance_id: ElectricalId
    layout: list[list[Annotated[StrictInt, Field(ge=0, le=10000)]]] = Field(min_length=1, max_length=64)
    pv_field_ids: list[ElectricalId] | None = Field(default=None, max_length=500)
    release_modules: StrictBool | None = None


class TableRef(ElectricalParameters):
    pv_field_id: ElectricalId
    table_id: ElectricalId


class ReplicatePatternParameters(ElectricalParameters):
    source_pv_field_id: ElectricalId
    source_table_id: ElectricalId
    targets: list[TableRef] | None = Field(default=None, max_length=5000)


_ELECTRICAL_PARAMETER_MODELS = {
    "create_string": CreateStringParameters, "assign_strings_to_mppt": AssignToMPPTParameters,
    "unassign_strings": StringIdsParameters, "delete_string": DeleteStringParameters,
    "create_strings": CreateStringsParameters, "assign_strings": AssignStringsParameters,
    "balance_mppt": InverterIdParameters, "suggest_string_length": SuggestStringLengthParameters,
    "inspect_inverter": InverterIdParameters,
    # S14a string edits.
    "split_string": SplitStringParameters, "join_strings": JoinStringsParameters,
    "reverse_string": DeleteStringParameters, "move_module": MoveModuleParameters,
    "swap_modules": SwapModulesParameters,
    # S14b: orientation policy, pairing, notation apply, replicate pattern.
    "set_orientation_tolerance": OrientationToleranceParameters, "set_orientation_override": OrientationOverrideParameters,
    "set_inverter_pairing": InverterPairingParameters, "apply_mppt_layout": MpptLayoutParameters,
    "replicate_pattern": ReplicatePatternParameters,
}
_READ_ONLY_ELECTRICAL_COMMANDS = {"suggest_string_length", "inspect_inverter"}


def _validated_electrical_commands(commands):
    for index, command in enumerate(commands):
        label = f"command {index} ({command.get('command_id', '<missing>')}, {command.get('command_type', '<missing>')})"
        error = next(_ELECTRICAL_COMMAND_VALIDATOR.iter_errors(command), None)
        if error is not None:
            path = ".".join(map(str, error.absolute_path)) or "command"
            raise ValueError(f"{label}: {path}: {error.message}")
        kind = command["command_type"]
        if kind == "add_inverter":
            raise ValueError(f"{label}: use POST /api/projects/{{id}}/inverters to pin the component revision")
        if kind == "commit_revision":
            raise ValueError(f"{label}: every successful request commits exactly once, implicitly")
        if kind in _READ_ONLY_ELECTRICAL_COMMANDS and len(commands) != 1:
            raise ValueError(f"{label}: a read-only command must be the only command in the batch")
        try:
            parameters = _ELECTRICAL_PARAMETER_MODELS[kind].model_validate(command["parameters"])
        except ValueError as exc:
            raise ValueError(f"{label}: {exc}") from exc
        yield {**command, "parameters": parameters.model_dump(exclude_none=True)}


class SceneParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class RotateParameters(SceneParameters):
    angle_deg: float
    origin: tuple[float, float] | None = None


class ScaleParameters(SceneParameters):
    factor: float = Field(gt=0, le=100)
    origin: tuple[float, float] | None = None


class MoveParameters(SceneParameters):
    dx_m: float
    dy_m: float


class CopyParameters(MoveParameters):
    """Offset of the duplicate from its source, metres; `with_pv` also copies a roof's PV fields (UX3 paste)."""
    with_pv: bool = False


class VertexParameters(SceneParameters):
    ring: StrictInt = Field(default=0, ge=0)
    vertex_index: StrictInt = Field(ge=0)
    target_x_m: float
    target_y_m: float
    snap_tolerance_m: float | None = Field(default=None, ge=0)
    snap_kinds: list[str] | None = None
    grid_spacing_m: float | None = Field(default=None, gt=0)
    snap_override: bool = False


class DimensionParameters(SceneParameters):
    edge_index: StrictInt = Field(ge=0)
    length_m: float = Field(gt=0)
    preserve: str = "start"
    source: str = "user_override"


class InsertVertexParameters(SceneParameters):
    ring: StrictInt = Field(default=0, ge=0)
    edge_index: StrictInt = Field(ge=0)
    x_m: float
    y_m: float


class DeleteVertexParameters(SceneParameters):
    ring: StrictInt = Field(default=0, ge=0)
    vertex_index: StrictInt = Field(ge=0)


class MoveEdgeParameters(SceneParameters):
    ring: StrictInt = Field(default=0, ge=0)
    edge_index: StrictInt = Field(ge=0)
    dx_m: float
    dy_m: float


class CentroidReference(SceneParameters):
    mode: Literal["boundary_centroid"]


class ExplicitReference(SceneParameters):
    mode: Literal["explicit_xy"]
    x_m: float = Field(ge=-50000, le=50000)
    y_m: float = Field(ge=-50000, le=50000)


class PlaneParameters(SceneParameters):
    slope_deg: float = Field(ge=0, lt=90)
    azimuth_deg: float = Field(ge=0, lt=360)
    base_elevation_m: float = Field(ge=-1000, le=10000)
    elevation_reference: CentroidReference | ExplicitReference | None = None


class HoleParameters(SceneParameters):
    vertices: list[tuple[float, float]] = Field(min_length=3)


class RemoveHoleParameters(SceneParameters):
    hole_index: StrictInt = Field(ge=0)


class HeightParameters(SceneParameters):
    height_m: float = Field(ge=0, le=1000)


class AngleParameters(SceneParameters):
    edge_index: StrictInt = Field(ge=0)
    azimuth_deg: float
    preserve: str = "start"


class ElevationParameters(SceneParameters):
    base_elevation_m: float


class PolygonParameters(SceneParameters):
    name: str = "Surface"
    surface_type: Literal[_SURFACE_TYPES]
    vertices: list[tuple[float, float]] = Field(min_length=3, max_length=1000)
    base_elevation_m: float = 0
    slope_deg: float = Field(default=0, ge=0, lt=90)
    azimuth_deg: float = Field(default=0, ge=0, lt=360)
    usable_for_pv: bool = True


class ExtrusionRequest(SceneParameters):
    name: str = "Obstacle"
    vertices: list[tuple[float, float]] = Field(min_length=3, max_length=1000)
    base_elevation_m: float = 0
    height_m: float = Field(ge=0)
    on_module_conflict: Literal["reject", "remove_modules", "refill_field"] = "reject"
    discard_dependent_strings: bool = False
    discard_manual_layout: bool = False
    dry_run: bool = False


class GroupParameters(SceneParameters):
    group_id: str = Field(min_length=1)
    name: str | None = Field(default=None, min_length=1, max_length=80)


class ReferenceAnchorParameters(SceneParameters):
    u: Literal["start", "center", "end"]
    v: Literal["start", "center", "end"]


_SCENE_PARAMETER_MODELS = {
    "set_reference_anchor": ReferenceAnchorParameters,
    "group": GroupParameters, "ungroup": SceneParameters,
    "edit_plane": PlaneParameters, "add_hole": HoleParameters, "remove_hole": RemoveHoleParameters,
    "insert_vertex": InsertVertexParameters, "delete_vertex": DeleteVertexParameters,
    "move_edge": MoveEdgeParameters, "edit_height": HeightParameters,
    "scale": ScaleParameters, "rotate": RotateParameters, "move": MoveParameters, "move_vertex": VertexParameters,
    "edit_exact_dimension": DimensionParameters, "edit_exact_angle": AngleParameters,
    "edit_elevation": ElevationParameters, "draw_polygon": PolygonParameters, "delete": SceneParameters,
    "copy": CopyParameters,
}


def _validated_scene_command(command):
    error = next(_SCENE_COMMAND_VALIDATOR.iter_errors(command), None)
    if error is not None:
        path = ".".join(map(str, error.absolute_path))
        raise ValueError(f"command{'.' + path if path else ''}: {error.message}")
    kind = command["command_type"]
    if kind not in _SCENE_PARAMETER_MODELS:
        why = ("; selection is session state" if kind in {"select", "multi_select"} else
               "; HTTP undo needs persisted history (deferred)" if kind in {"undo", "redo"} else "")
        raise ValueError(f"command_type {kind} is not supported by /scene/commands yet{why}")
    count = len(command["target_entity_ids"])
    if ((kind == "draw_polygon" and count != 0) or (kind in {"delete", "group", "ungroup"} and count < 1)
            or (kind not in {"draw_polygon", "delete", "group", "ungroup"} and count != 1)):
        raise ValueError(f"target_entity_ids has invalid count for {kind}")
    parameters = _SCENE_PARAMETER_MODELS[kind].model_validate(command["parameters"])
    return {**command, "parameters": parameters.model_dump(exclude_none=True)}


class BoxObstacleRequest(BaseModel):
    name: str = "Obstacle"
    origin_x_m: float
    origin_y_m: float
    width_m: float = Field(gt=0)
    depth_m: float = Field(gt=0)
    base_elevation_m: float = 0.0
    height_m: float = Field(ge=0)
    on_module_conflict: Literal["reject", "remove_modules", "refill_field"] = "reject"
    discard_dependent_strings: bool = False
    discard_manual_layout: bool = False
    dry_run: bool = False


class PVFieldRequest(BaseModel):
    rows_per_table: int = Field(1, ge=1, le=10)
    leftover_depth: Literal["smaller_table", "smaller_table_front", "leave_empty"] = "smaller_table"
    name: str = "PV field"
    support_surface_id: str
    module_definition_revision_id: str
    orientation: str = "portrait"
    azimuth_deg: float = Field(default=0, ge=0, lt=360)
    tilt_deg: float = 10.0
    module_gap_x_m: float = Field(default=0.02, ge=0)
    module_gap_y_m: float = Field(default=0.02, ge=0)
    row_pitch_m: float = Field(default=2.6, gt=0)
    mounting_height_m: float = Field(default=0.2, ge=0)
    perimeter_setback_m: float = Field(default=0.3, ge=0)
    obstacle_setback_m: float = Field(default=0.3, ge=0)
    row_alignment: Literal["start", "center", "end"] = "start"
    depth_alignment: Literal["start", "center", "end"] | None = None


class PVFieldUpdateRequest(BaseModel):
    rows_per_table: int | None = Field(None, ge=1, le=10)
    leftover_depth: Literal["smaller_table", "smaller_table_front", "leave_empty"] | None = None
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    module_definition_revision_id: str | None = None
    orientation: str | None = None
    azimuth_deg: float | None = Field(default=None, ge=0, lt=360)
    tilt_deg: float | None = None
    module_gap_x_m: float | None = Field(default=None, ge=0)
    module_gap_y_m: float | None = Field(default=None, ge=0)
    row_pitch_m: float | None = Field(default=None, gt=0)
    mounting_height_m: float | None = Field(default=None, ge=0)
    perimeter_setback_m: float | None = Field(default=None, ge=0)
    obstacle_setback_m: float | None = Field(default=None, ge=0)
    row_alignment: Literal["start", "center", "end"] | None = None
    depth_alignment: Literal["start", "center", "end"] | None = None
    discard_dependent_strings: bool = False
    discard_manual_layout: bool = False
    dry_run: bool = False


class ModuleCommandsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: Literal["delete_modules", "move_modules"]
    module_instance_ids: list[StrictStr] = Field(min_length=1, max_length=10000)
    dx_m: float | None = Field(default=None, ge=-10000, le=10000, allow_inf_nan=False, strict=True)
    dy_m: float | None = Field(default=None, ge=-10000, le=10000, allow_inf_nan=False, strict=True)
    discard_dependent_strings: bool = False
    dry_run: bool = False
    on_conflict: Literal["reject", "fill"] = "reject"

    @model_validator(mode="after")
    def validate_command(self):
        if len(set(self.module_instance_ids)) != len(self.module_instance_ids):
            raise ValueError("module_instance_ids must be unique")
        if self.command == "move_modules" and (self.dx_m is None or self.dy_m is None):
            raise ValueError("move_modules requires dx_m and dy_m")
        if self.command == "delete_modules" and self.model_fields_set.intersection({"dx_m", "dy_m"}):
            raise ValueError("dx_m and dy_m are forbidden for delete_modules")
        if self.command == "delete_modules" and "on_conflict" in self.model_fields_set:
            raise ValueError("on_conflict is forbidden for delete_modules")
        return self


class InverterRequest(BaseModel):
    inverter_definition_revision_id: str
    name: str = "Inverter"


class InverterDefinitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inverter_definition_revision_id: str = Field(min_length=1)


class ShadingFreePitchRequest(BaseModel):
    rows_per_table: int = Field(1, ge=1, le=10)
    module_gap_y_m: float = Field(0, ge=0)
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    module_definition_revision_id: str = Field(min_length=1)
    orientation: Literal["portrait", "landscape"]
    tilt_deg: float = Field(ge=0, lt=90)
    design_sun_elevation_deg: float = Field(gt=0, lt=90)
    sun_azimuth_offset_deg: float = Field(default=0.0, ge=-180, le=180)


class SuggestLayoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pv_field_ids: list[str] | None = Field(default=None, max_length=500)


class StringingRequest(BaseModel):
    string_length: int = Field(ge=1)
    pv_field_id: str | None = None
    allow_shorter_remainder: bool = False


class AssignmentRequest(BaseModel):
    inverter_instance_id: str
    string_ids: list[str] | None = None


class WeatherAcquireRequest(BaseModel):
    source_id: str
    start_date: str
    end_date: str


class ElectricalShadingSelectionRequest(BaseModel):
    module_revision_id: str = Field(min_length=1)
    requested_fidelity: str = Field(min_length=1)
    fallback_policy: str = "fail_closed"
    topology_revision_id: str | None = None
    region_parameterization_evidence_id: str | None = None
    cell_parameterization_evidence_id: str | None = None


class ElectricalShadingAssetImportRequest(BaseModel):
    asset_kind: str = Field(min_length=1)
    asset: dict[str, Any]
    sources: list[dict[str, Any]]


class Level1ModuleSnapshotRequest(BaseModel):
    module_instance_id: str = Field(min_length=1)
    sun_vector_xyz: list[float] = Field(min_length=3, max_length=3)
    unshaded_poa: dict[str, float]
    optical_modifier: dict[str, float]
    optical_model_manifest: dict[str, Any]
    module_temperature_c: float
    interval_start: str = Field(min_length=1)
    evaluation_time: str = Field(min_length=1)
    self_shading_enabled: bool
    sky_dome_resolution: dict[str, Any]
    ground_dome_resolution: dict[str, Any]
    geometric_fidelity_level: str = "engineering"


def _translate(action: Callable[[], T]) -> T:
    try:
        return action()
    except HistoryConflictError as exc:
        raise HTTPException(status_code=409, detail={"reason": exc.reason, "message": str(exc)}) from exc
    except GeometryBatchError as exc:
        raise HTTPException(status_code=422, detail=exc.detail) from exc
    except DependentFieldError as exc:
        raise HTTPException(status_code=422, detail={"message": str(exc), "dependent_fields": exc.dependent_fields}) from exc
    except GeometryConflictError as exc:
        detail = {"message": str(exc), "conflicts": exc.conflicts}
        if hasattr(exc, "reasons"):
            detail["reasons"] = exc.reasons
        if exc.options is not None:
            detail["options"] = exc.options
        raise HTTPException(status_code=422, detail=detail) from exc
    except TopologyConsistencyError as exc:
        raise HTTPException(status_code=422, detail={"message": str(exc), "findings": exc.findings}) from exc
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"project not found: {exc.args[0]}") from exc
    # DATA1: a damaged or newer project file is a 409 the browser can act on (restore a backup / update the app).
    except ProjectCorruptError as exc:
        raise HTTPException(status_code=409, detail={"code": "project_unreadable", "project_id": exc.project_id, "message": str(exc)}) from exc
    except ProjectVersionError as exc:
        raise HTTPException(status_code=409, detail={"code": "project_too_new" if exc.newer else "project_unreadable", "project_id": exc.project_id, "message": str(exc)}) from exc
    except (ProjectBusyError, ProjectConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except WeatherAcquisitionError as exc:
        cause = exc.__cause__
        if exc.finding_code == "WX_PROVIDER_HTTP_ERROR" and isinstance(cause, HTTPError) and 400 <= cause.code < 500:
            raise HTTPException(status_code=422, detail=(
                f"requested period is not available from the provider (HTTP {cause.code}: {cause.reason})"
            )) from exc
        detail = exc.args[0] if exc.args else str(exc)
        status_code = (
            503
            if exc.finding_code in {"WX_PROVIDER_UNAVAILABLE", "WX_PROVIDER_HTTP_ERROR"}
            else 422
        )
        raise HTTPException(status_code=status_code, detail=str(detail)) from exc
    except (ValueError, KeyError) as exc:
        detail = exc.args[0] if exc.args else str(exc)
        raise HTTPException(status_code=422, detail=str(detail)) from exc


def create_app(*, store_root: str | Path | None = None, library_root: str | Path | None = None) -> FastAPI:
    selected_root = Path(
        store_root
        or os.environ.get("RAWIBUMI_PROJECT_STORE")
        or os.environ.get("OPENSIMPV_PROJECT_STORE")  # legacy pre-rename fallback
        or ROOT / "var" / "projects"
    )
    service = ProjectShellService(FileProjectStore(selected_root), library_root=library_root)
    study = BrowserStudyService(
        service,
        weather_root=selected_root.parent / "weather",
        run_root=selected_root.parent / "runs",
        snapshot_root=selected_root.parent / "weather-snapshots",
    )

    app = FastAPI(
        title="RawiBumi API",
        version="0.1-phase64",
        strict_content_type=True,
    )
    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logger.error("Unexpected API request failure", exc_info=(type(exc), exc, exc.__traceback__))
        return JSONResponse(status_code=500, content={"detail": {
            "code": "unexpected_error",
            "message": "The request could not be completed. Please try again.",
        }})

    app.state.project_service = service
    # Private invite-only test windows (BETA1); the module is not part of the public edition, so import it only when asked.
    beta_window = os.environ.get("RAWIBUMI_BETA_WINDOW")
    if beta_window:
        from .beta_gate import install as install_beta_gate
        install_beta_gate(app, beta_window)
    app.state.study_service = study
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "phase": "6.4"}

    @app.get("/api/simulation-defaults")
    def get_simulation_defaults() -> dict[str, Any]:
        return simulation_defaults()

    @app.get("/api/catalog")
    def catalog() -> dict[str, Any]:
        return service.catalog_view()

    def library_call(operation):
        from .component_library import ComponentLibraryError
        try:
            return operation()
        except ComponentLibraryError as exc:
            if isinstance(exc.__cause__, (TypeError, KeyError, IndexError, OverflowError)):
                raise exc.__cause__
            raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
        except AssertionError as exc:
            logger.exception("Component library identity check failed")
            raise HTTPException(status_code=500, detail={"message": "A component library identity collision was detected.", "code": "component_revision_collision"}) from exc
        except OSError as exc:
            logger.exception("Component library storage failed")
            raise HTTPException(status_code=503, detail={"message": "The component library could not be read or saved.", "code": "component_library_unavailable"}) from exc

    @app.post("/api/component-library/imports")
    async def import_component(request: Request, filename: str, dry_run: bool = False):
        from .component_library import MAX_IMPORT_BYTES
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > MAX_IMPORT_BYTES:
                raise HTTPException(status_code=413, detail={"message": "Component files must be no larger than 2 MiB.", "code": "component_file_too_large"})
            data.extend(chunk)
        result = await run_in_threadpool(library_call, lambda: service.library.import_bytes(filename, bytes(data), dry_run=dry_run))
        if not dry_run:
            service.refresh_catalog()
        return result["entry"] if dry_run else result

    @app.post("/api/component-library/{revision_id}/complete")
    async def complete_component(revision_id: str, request: Request):
        try:
            payload = await request.json()
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(status_code=422, detail={"message": "Completion requires a JSON body.", "code": "completion_invalid"}) from exc
        result = await run_in_threadpool(library_call, lambda: service.library.complete(revision_id, payload))
        if not payload.get("dry_run", False):
            service.refresh_catalog()
        return result["entry"] if payload.get("dry_run", False) else result

    @app.get("/api/component-library")
    def component_library(include_hidden: bool = False):
        return library_call(lambda: service.library.view_entries(include_hidden=include_hidden))

    @app.post("/api/component-library/{revision_id}/hide")
    def hide_component(revision_id: str):
        entry = library_call(lambda: service.library.set_hidden(revision_id, True))
        service.refresh_catalog()
        return entry

    @app.post("/api/component-library/{revision_id}/unhide")
    def unhide_component(revision_id: str):
        entry = library_call(lambda: service.library.set_hidden(revision_id, False))
        service.refresh_catalog()
        return entry

    def restore_history(project_id, request, *, redo=False):
        with study._operation_lock:
            return _translate(lambda: service.restore_history(project_id, redo=redo,
                **request.model_dump(), require_idle=study._require_idle, weather_store=study.weather))

    @app.post("/api/projects/{project_id}/undo")
    def undo_project(project_id: str, request: HistoryRequest):
        return restore_history(project_id, request)

    @app.post("/api/projects/{project_id}/redo")
    def redo_project(project_id: str, request: HistoryRequest):
        return restore_history(project_id, request, redo=True)

    @app.get("/api/projects")
    def list_projects() -> list[dict[str, Any]]:
        return service.list_projects()

    @app.get("/api/projects/{project_id}/systems/overview")
    def systems_overview(project_id: str):
        return _translate(lambda: service.systems_overview(project_id))

    @app.get("/api/projects/{project_id}/summary")
    def project_summary(project_id: str) -> dict[str, Any]:
        return _translate(lambda: service.project_summary(project_id))

    @app.post("/api/projects", status_code=201)
    def create_project(request: CreateProjectRequest) -> dict[str, Any]:
        bundle = _translate(
            lambda: service.create_project(
                name=request.name,
                latitude_deg=request.latitude_deg,
                longitude_deg=request.longitude_deg,
                timezone_name=request.timezone,
                elevation_m=request.elevation_m,
                workspace_mode=request.workspace_mode,
                description=request.description,
            )
        )
        return _translate(
            lambda: service.project_view(bundle["project"]["project_id"])
        )

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str) -> dict[str, Any]:
        return _translate(lambda: service.project_view(project_id))

    @app.patch("/api/projects/{project_id}")
    def update_project(project_id: str, request: ProjectPatchRequest) -> dict[str, Any]:
        return _translate(lambda: service.update_project(project_id, **request.model_dump(exclude_unset=True)))

    @app.patch("/api/projects/{project_id}/shading-accuracy")
    def update_shading_accuracy(project_id: str, request: dict[str, Any]) -> dict[str, Any]:
        return _translate(lambda: service.update_shading_accuracy(project_id, request))

    @app.patch("/api/projects/{project_id}/optics-thermal")
    def update_optics_thermal(project_id: str, request: dict[str, Any]) -> dict[str, Any]:
        return _translate(lambda: service.update_optics_thermal(project_id, request))

    @app.patch("/api/projects/{project_id}/losses")
    def update_losses(project_id: str, request: dict[str, Any]) -> dict[str, Any]:
        return _translate(lambda: service.update_losses(project_id, request))

    @app.patch("/api/projects/{project_id}/site")
    def update_site(project_id: str, request: SitePatchRequest) -> dict[str, Any]:
        return _translate(lambda: study.update_site(project_id, **request.model_dump(exclude_unset=True)))

    @app.patch("/api/projects/{project_id}/site/details")
    def update_site_details(project_id: str, request: SiteDetailsPatchRequest) -> dict[str, Any]:
        return _translate(lambda: service.update_site_details(project_id, **request.model_dump(exclude_unset=True)))

    @app.delete("/api/projects/{project_id}")
    def delete_project(project_id: str, confirm: str | None = None) -> dict[str, Any]:
        return _translate(lambda: study.delete_project(project_id, confirm=confirm))

    # ---- DATA1: project files, backups ----
    def archive_call(operation):
        from .project_archive import ArchiveError
        def guarded():
            # Before _translate: an ArchiveError is a ValueError, but carries its own status and code.
            try:
                return operation()
            except ArchiveError as exc:
                raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
        return _translate(guarded)

    @app.get("/api/projects/{project_id}/export")
    def export_project(project_id: str, include_results: bool = True):
        from .project_archive import export_project as build
        filename, data = archive_call(lambda: build(service, study, project_id, include_results=include_results))
        return Response(content=data, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"', "X-Content-Type-Options": "nosniff"})

    @app.post("/api/projects/import")
    async def import_project(request: Request, filename: str = "project.rawibumi", replace: bool = False):
        from .project_archive import MAX_UNCOMPRESSED, import_project as load
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > MAX_UNCOMPRESSED:
                raise HTTPException(status_code=413, detail={"code": "archive_too_large", "message": "Project files must be no larger than 2 GB."})
            data.extend(chunk)
        return await run_in_threadpool(archive_call, lambda: load(service, study, bytes(data), replace=replace))

    @app.get("/api/projects/{project_id}/backups")
    def project_backups(project_id: str):
        def read():
            if not service.store.path_for(project_id).exists():
                raise ProjectNotFoundError(project_id)
            return service.store.backups(project_id)
        return _translate(read)

    @app.post("/api/projects/{project_id}/backups/{backup_id}/restore")
    def restore_project_backup(project_id: str, backup_id: str):
        from .project_archive import restore_backup
        return archive_call(lambda: restore_backup(service, study, project_id, backup_id))

    @app.get("/api/projects/{project_id}/electrical-shading/capability")
    def electrical_shading_capability(
        project_id: str,
        module_revision_id: str,
        topology_revision_id: str | None = None,
        region_parameterization_evidence_id: str | None = None,
        cell_parameterization_evidence_id: str | None = None,
    ) -> dict[str, Any]:
        return _translate(
            lambda: service.module_electrical_shading_capability(
                project_id,
                module_revision_id=module_revision_id,
                topology_revision_id=topology_revision_id,
                region_parameterization_evidence_id=(
                    region_parameterization_evidence_id
                ),
                cell_parameterization_evidence_id=(
                    cell_parameterization_evidence_id
                ),
            )
        )

    @app.post("/api/projects/{project_id}/electrical-shading/selection")
    def set_electrical_shading_selection(
        project_id: str,
        request: ElectricalShadingSelectionRequest,
    ) -> dict[str, Any]:
        return _translate(
            lambda: service.set_module_electrical_shading_selection(
                project_id,
                **request.model_dump(),
            )
        )

    @app.post("/api/projects/{project_id}/electrical-shading/assets/import")
    def import_electrical_shading_asset(
        project_id: str,
        request: ElectricalShadingAssetImportRequest,
    ) -> dict[str, Any]:
        return _translate(
            lambda: service.import_electrical_shading_asset(
                project_id,
                **request.model_dump(),
            )
        )


    @app.get("/api/projects/{project_id}/electrical-shading/region-map")
    def electrical_region_map(
        project_id: str,
        module_instance_id: str,
    ) -> dict[str, Any]:
        return _translate(
            lambda: service.electrical_region_map(
                project_id,
                module_instance_id=module_instance_id,
            )
        )

    @app.post("/api/projects/{project_id}/electrical-shading/level1-module-snapshot")
    def level1_module_snapshot(
        project_id: str,
        request: Level1ModuleSnapshotRequest,
    ) -> dict[str, Any]:
        return _translate(
            lambda: service.level1_module_snapshot(
                project_id,
                **request.model_dump(),
            )
        )

    @app.patch("/api/projects/{project_id}/workspace")
    def update_workspace(
        project_id: str,
        request: WorkspaceModeRequest,
    ) -> dict[str, Any]:
        _translate(lambda: service.set_workspace_mode(project_id, request.mode))
        return _translate(lambda: service.project_view(project_id))

    @app.post("/api/projects/{project_id}/surfaces/rectangle")
    def add_surface(
        project_id: str,
        request: SurfaceRectangleRequest,
    ) -> dict[str, Any]:
        return _translate(
            lambda: service.add_surface_rectangle(
                project_id,
                **request.model_dump(),
            )
        )

    @app.post("/api/projects/{project_id}/scene/move")
    def move_scene_entity(
        project_id: str,
        request: SceneMoveRequest,
    ) -> dict[str, Any]:
        return _translate(
            lambda: service.move_scene_entity(
                project_id,
                **request.model_dump(),
            )
        )

    @app.post("/api/projects/{project_id}/obstacles/box")
    def add_obstacle(
        project_id: str,
        request: BoxObstacleRequest,
    ) -> dict[str, Any]:
        return _translate(
            lambda: service.add_box_obstacle(
                project_id,
                **request.model_dump(),
            )
        )

    @app.post("/api/projects/{project_id}/scene/geometry")
    async def scene_geometry(project_id: str, request: Request):
        data=bytearray()
        async for chunk in request.stream():
            if len(data)+len(chunk)>MAX_GEOMETRY_BYTES:
                raise HTTPException(status_code=413,detail={"code":"geometry_payload_too_large","message":"Geometry JSON must be no larger than 16 MiB.","operation_index":None,"operation_id":None,"object_id":None,"findings":[]})
            data.extend(chunk)
        try:
            payload=json.loads(data)
            if not isinstance(payload,dict) or "operations" not in payload or set(payload)-{"operations","dry_run","discard_dependent_strings"}:
                raise ValueError("Geometry request must contain operations and optional dry_run/discard_dependent_strings only")
        except (ValueError,TypeError,UnicodeDecodeError) as exc:
            raise HTTPException(status_code=422,detail=GeometryBatchError(str(exc)).detail) from exc
        return await run_in_threadpool(lambda:_translate(lambda:service.scene_geometry(project_id,**payload)))

    @app.get("/api/projects/{project_id}/scene/geometry-3d")
    def scene_geometry_3d(project_id: str):
        return _translate(lambda:service.scene_geometry_3d(project_id))

    @app.post("/api/projects/{project_id}/scene/commands")
    def scene_command(project_id: str, request: SceneCommandRequest) -> dict[str, Any]:
        def apply():
            command = _validated_scene_command(request.command)
            try:
                return service.scene_command(project_id, command, **request.model_dump(exclude={"command"}))
            except IndexError as exc:
                raise ValueError(str(exc)) from exc
        return _translate(apply)

    @app.post("/api/projects/{project_id}/obstacles/extrusion")
    def add_polygon_obstacle(project_id: str, request: ExtrusionRequest) -> dict[str, Any]:
        return _translate(lambda: service.add_polygon_obstacle(project_id, **request.model_dump()))

    @app.post("/api/projects/{project_id}/electrical/commands")
    def electrical_commands(project_id: str, request: ElectricalCommandsRequest) -> dict[str, Any]:
        return _translate(lambda: service.electrical_commands(
            project_id, _validated_electrical_commands(request.commands), dry_run=request.dry_run,
        ))

    @app.exception_handler(RequestValidationError)
    async def scene_request_validation_error(request, exc):
        if getattr(request.scope.get("route"), "name", None) in {
            "import_component", "component_library", "hide_component", "unhide_component",
        }:
            return JSONResponse(status_code=422, content={"detail": {
                "message": "The component library request is invalid. Check the filename and query options.",
                "code": "invalid_component_library_request",
                "errors": _finite_error_values(jsonable_encoder(exc.errors())),
            }})
        if getattr(request.scope.get("route"), "name", None) == "module_commands":
            message = str(exc)
            return JSONResponse(status_code=422, content={"detail": {"message": message, "reasons": [
                {"code": "module_command_invalid", "count": 0, "message": message}],
                "errors": _finite_error_values(jsonable_encoder(exc.errors()))}})
        # Pydantic's errors retain the input NaN/inf. Render new-route errors as
        # text so error JSON itself stays finite; other route contracts are kept.
        if getattr(request.scope.get("route"), "name", None) in {
            "scene_command", "add_polygon_obstacle", "electrical_commands", "update_project", "update_site", "update_site_details", "update_losses", "update_optics_thermal", "update_shading_accuracy",
        }:
            return JSONResponse(status_code=422, content={"detail": str(exc)})
        return JSONResponse(status_code=422, content={"detail": _finite_error_values(jsonable_encoder(exc.errors()))})

    @app.post("/api/projects/{project_id}/pv-fields")
    def add_pv_field(
        project_id: str,
        request: PVFieldRequest,
    ) -> dict[str, Any]:
        return _translate(
            lambda: service.create_pv_field(
                project_id,
                **request.model_dump(),
            )
        )

    @app.post("/api/projects/{project_id}/pv-fields/modules/commands")
    def module_commands(project_id: str, request: ModuleCommandsRequest) -> dict[str, Any]:
        def apply():
            with study._project_operation(project_id):
                return service.module_commands(project_id, **request.model_dump())
        try:
            return _translate(apply)
        except HTTPException as exc:
            if exc.status_code == 422:
                detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
                detail.setdefault("reasons", [{"code": "module_command_invalid", "count": len(request.module_instance_ids),
                                                "message": detail["message"]}])
                exc.detail = detail
            raise

    @app.patch("/api/projects/{project_id}/pv-fields/{field_id}")
    def update_pv_field(project_id: str, field_id: str, request: PVFieldUpdateRequest) -> dict[str, Any]:
        return _translate(lambda: service.update_pv_field(
            project_id, field_id, **request.model_dump(exclude_unset=True, exclude_none=True),
        ))

    @app.delete("/api/projects/{project_id}/pv-fields/{field_id}")
    def delete_pv_field(project_id: str, field_id: str, discard_dependent_strings: bool = False,
                        dry_run: bool = False) -> dict[str, Any]:
        return _translate(lambda: service.delete_pv_field(
            project_id, field_id, discard_dependent_strings=discard_dependent_strings, dry_run=dry_run,
        ))

    @app.post("/api/projects/{project_id}/inverters")
    def add_inverter(
        project_id: str,
        request: InverterRequest,
    ) -> dict[str, Any]:
        return _translate(
            lambda: service.add_inverter(
                project_id,
                **request.model_dump(),
            )
        )

    @app.post("/api/projects/{project_id}/pv-fields/shading-free-pitch")
    def shading_free_pitch(project_id: str, request: ShadingFreePitchRequest) -> dict[str, Any]:
        return _translate(lambda: service.shading_free_pitch(project_id, **request.model_dump()))

    @app.delete("/api/projects/{project_id}/inverters/{inverter_instance_id}")
    def remove_inverter(project_id: str, inverter_instance_id: str) -> dict[str, Any]:
        return _translate(lambda: service.remove_inverter(project_id, inverter_instance_id))

    @app.put("/api/projects/{project_id}/inverters/{inverter_instance_id}")
    def change_inverter_definition(project_id: str, inverter_instance_id: str,
                                   request: InverterDefinitionRequest) -> dict[str, Any]:
        return _translate(lambda: service.change_inverter_definition(
            project_id, inverter_instance_id, **request.model_dump()))

    @app.get("/api/projects/{project_id}/inverters/{inverter_instance_id}/sizing")
    def inverter_sizing(project_id: str, inverter_instance_id: str):
        return _translate(lambda: service.inverter_sizing(project_id, inverter_instance_id))

    @app.post("/api/projects/{project_id}/inverters/{inverter_instance_id}/suggest-layout")
    def suggest_mppt_layout(project_id: str, inverter_instance_id: str,
                            request: SuggestLayoutRequest) -> dict[str, Any]:
        return _translate(lambda: service.suggest_mppt_layout(
            project_id, inverter_instance_id, request.pv_field_ids))

    @app.post("/api/projects/{project_id}/strings")
    def create_strings(
        project_id: str,
        request: StringingRequest,
    ) -> dict[str, Any]:
        return _translate(
            lambda: service.create_strings(
                project_id,
                **request.model_dump(),
            )
        )

    @app.post("/api/projects/{project_id}/assignments")
    def assign_strings(
        project_id: str,
        request: AssignmentRequest,
    ) -> dict[str, Any]:
        return _translate(
            lambda: service.assign_strings(
                project_id,
                **request.model_dump(),
            )
        )


    @app.get("/api/weather-sources")
    def weather_sources() -> list[dict[str, Any]]:
        return study.weather_sources()

    @app.post("/api/projects/{project_id}/weather/acquire")
    def acquire_weather(
        project_id: str,
        request: WeatherAcquireRequest,
    ) -> dict[str, Any]:
        return _translate(
            lambda: study.acquire_weather(
                project_id,
                source_id=request.source_id,
                start_date=request.start_date,
                end_date=request.end_date,
            )
        )

    @app.post("/api/projects/{project_id}/weather/import")
    async def import_weather_file(project_id: str, request: Request, filename: str,
                                  dry_run: bool = False, accept_distant_location: bool = False):
        from .study import MAX_WEATHER_IMPORT_BYTES, WeatherImportError
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > MAX_WEATHER_IMPORT_BYTES:
                raise HTTPException(status_code=413, detail={"code": "weather_file_too_large", "message": "Weather files must be no larger than 50 MiB."})
            data.extend(chunk)
        def apply():
            try:
                return study.import_weather(project_id, filename=filename, data=bytes(data), dry_run=dry_run,
                    accept_distant_location=accept_distant_location)
            except WeatherImportError as exc:
                raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
            except OSError as exc:
                logger.exception("Weather import storage failed")
                raise HTTPException(status_code=503, detail={"code": "weather_storage_unavailable", "message": "The weather file could not be saved or read."}) from exc
        return await run_in_threadpool(_translate, apply)

    # ---- UX1 imagery: overlay assets and the persisted MapLayerConfiguration ----
    def imagery_call(operation):
        from .imagery import ImageryError
        try:
            return operation()
        except ImageryError as exc:
            raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
        except OSError as exc:
            raise HTTPException(status_code=503, detail={"code": "imagery_storage_unavailable", "message": "The overlay image could not be saved or read."}) from exc

    @app.post("/api/projects/{project_id}/imagery/assets")
    async def import_imagery_asset(project_id: str, request: Request, filename: str):
        from .imagery import MAX_IMAGE_BYTES
        _translate(lambda: service.get_bundle(project_id))
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > MAX_IMAGE_BYTES:
                raise HTTPException(status_code=413, detail={"code": "imagery_too_large", "message": "Overlay images must be no larger than 10 MB."})
            data.extend(chunk)
        return await run_in_threadpool(imagery_call, lambda: service.imagery.put(project_id, filename, bytes(data)))

    @app.get("/api/projects/{project_id}/imagery/assets/{asset_id}")
    def imagery_asset(project_id: str, asset_id: str):
        _translate(lambda: service.get_bundle(project_id))
        record, data = imagery_call(lambda: service.imagery.read(project_id, asset_id))
        return Response(content=data, media_type=record["mime"], headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=31536000, immutable"})

    @app.put("/api/projects/{project_id}/imagery")
    async def update_imagery(project_id: str, request: Request):
        try:
            config = await request.json()
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(status_code=422, detail={"code": "imagery_invalid", "message": "Imagery requires a JSON body."}) from exc
        return _translate(lambda: imagery_call(lambda: service.update_imagery(project_id, config)))

    @app.get("/api/projects/{project_id}/execution-readiness")
    def execution_readiness(project_id: str, requested_fidelity: Literal["level_2_bypass_substring"] | None = None,
                            fallback_policy: Literal["fail_closed", "explicit_lower_fidelity"] = "fail_closed") -> dict[str, Any]:
        request = None if requested_fidelity is None else {"requested_fidelity": requested_fidelity, "fallback_policy": fallback_policy}
        return _translate(lambda: study.execution_readiness(project_id, request))

    @app.get("/api/projects/{project_id}/runs")
    def simulation_runs(project_id: str) -> list[dict[str, Any]]:
        return _translate(lambda: study.runs(project_id))

    @app.get("/api/projects/{project_id}/runs/{run_id}/result")
    def simulation_run_result(project_id: str, run_id: str) -> dict[str, Any]:
        return _translate(lambda: study.run_result(project_id, run_id))

    @app.get("/api/projects/{project_id}/runs/{run_id}/annual-pxx")
    def run_annual_pxx(project_id: str, run_id: str) -> dict[str, Any]:
        return _translate(lambda: study.annual_pxx(project_id, run_id))

    @app.put("/api/projects/{project_id}/uncertainty-assumptions")
    def put_uncertainty_assumptions(project_id: str, request: UncertaintyAssumptionsRequest) -> dict[str, Any]:
        return _translate(lambda: service.update_uncertainty_assumptions(project_id, request.ledger))

    @app.get("/api/projects/{project_id}/runs/{run_id}/timeseries")
    def run_timeseries(project_id: str, run_id: str) -> dict[str, Any]:
        return _translate(lambda: study.run_series(project_id, run_id))

    @app.get("/api/projects/{project_id}/runs/{run_id}/report-snapshot")
    def report_snapshot(project_id: str, run_id: str) -> Response:
        content = _translate(lambda: study.report_snapshot(project_id, run_id))
        from engine.simulation.artifacts import canonical_json_bytes
        return Response(canonical_json_bytes(content), media_type="application/json", headers={"Cache-Control": "no-store"})

    @app.get("/api/projects/{project_id}/runs/{run_id}/exports/free-csv")
    def free_csv_export(project_id: str, run_id: str) -> Response:
        content = _translate(lambda: study.free_csv_export(project_id, run_id))
        return Response(content, media_type="application/zip", headers={
            "Content-Disposition": 'attachment; filename="RawiBumi_free_csv.zip"',
            "Cache-Control": "no-store",
        })

    @app.get("/api/projects/{project_id}/runs/{run_id}/exports/schema")
    def numerical_csv_schema(project_id: str, run_id: str) -> dict[str, Any]:
        return _translate(lambda: study.csv_export_schema(project_id, run_id))

    @app.get("/api/reporting/native-pdf/capability")
    def native_pdf_capability(response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return {"enabled": _community_native_pdf_enabled(), "format": "pdf",
                "text_based": True, "locales": ["en", "id"]}

    def native_pdf_response(project_id: str, run_id: str, locale: str = "en", plan_figure_png=None) -> Response:
        headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
        # Check before service access, including invalid locales in denied mode.
        if not _community_native_pdf_enabled():
            raise HTTPException(404, "Native PDF download is unavailable.", headers=headers)
        if locale not in {"en", "id"}:
            raise HTTPException(422, "Native PDF locale must be en or id.", headers=headers)
        try:
            if plan_figure_png is None:
                content = study.native_pdf_document(project_id, run_id, locale=locale)
            else:
                content = study.native_pdf_document(project_id, run_id, locale=locale, plan_figure_png=plan_figure_png)
        except NativePDFError as exc:
            logger.warning("Native PDF renderer unavailable", exc_info=True)
            raise HTTPException(503, "Native PDF service is unavailable. Please retry later.", headers=headers) from exc
        except (ProjectNotFoundError, FileNotFoundError) as exc:
            raise HTTPException(404, "Verified report is unavailable for this project and run.", headers=headers) from exc
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, "Verified report is unavailable for this project and run.", headers=headers) from exc
        except Exception as exc:
            # Native PDF has its own sanitized boundary; CSV retains _translate.
            logger.exception("Native PDF download failed")
            raise HTTPException(500, "Native PDF download failed.", headers=headers) from exc
        if not isinstance(content, bytes) or not 5 <= len(content) <= MAX_PDF_BYTES or not content.startswith(b"%PDF-"):
            logger.error("Native PDF service returned invalid or oversized bytes")
            raise HTTPException(500, "Native PDF download failed.", headers=headers)
        return Response(content, media_type="application/pdf", headers={
            **headers,
            "Content-Disposition": 'attachment; filename="RawiBumi_verified_report.pdf"',
        })

    @app.get("/api/projects/{project_id}/runs/{run_id}/exports/native-pdf")
    def native_pdf_download(project_id: str, run_id: str, locale: str = "en") -> Response:
        return native_pdf_response(project_id, run_id, locale)

    class NativePDFDownloadRequest(BaseModel):
        model_config = ConfigDict(extra="forbid")
        locale: StrictStr = "en"
        plan_figure_png: StrictStr | None = Field(default=None, max_length=5592430)

    @app.post("/api/projects/{project_id}/runs/{run_id}/exports/native-pdf")
    async def native_pdf_download_post(project_id: str, run_id: str, request: Request) -> Response:
        headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
        if not _community_native_pdf_enabled():
            raise HTTPException(404, "Native PDF download is unavailable.", headers=headers)
        # Explicit parsing preserves denial precedence over all body validation.
        try:
            declared_length = int(request.headers.get("content-length", "0"))
            if declared_length < 0:
                raise ValueError("negative length")
        except ValueError:
            raise HTTPException(422, "Native PDF request Content-Length is invalid.", headers=headers)
        if declared_length > 6 * 1024 * 1024:
            raise HTTPException(422, "Native PDF request exceeds the image size limit.", headers=headers)
        try:
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > 6 * 1024 * 1024:
                    raise ValueError("oversize body")
                body.extend(chunk)
            value = NativePDFDownloadRequest.model_validate(json.loads(body))
        except (ValueError, TypeError):
            raise HTTPException(422, "Native PDF request needs only locale and optional plan_figure_png.", headers=headers)
        if value.locale not in {"en", "id"}:
            raise HTTPException(422, "Native PDF locale must be en or id.", headers=headers)
        from reporting.exports.native_pdf import validate_plan_png
        try:
            clean = await run_in_threadpool(validate_plan_png, value.plan_figure_png)
        except ValueError as exc:
            raise HTTPException(422, str(exc), headers=headers) from exc
        return await run_in_threadpool(native_pdf_response, project_id, run_id, value.locale, clean)

    @app.post("/api/projects/{project_id}/runs/{run_id}/exports")
    def numerical_csv_export(project_id: str, run_id: str, request: NumericalCSVExportRequest) -> Response:
        content = _translate(lambda: study.csv_export(project_id, run_id, request.columns,
                                                      formats=tuple(request.formats or ("csv",)), deliverable=request.deliverable))
        name = "RawiBumi_results_bundle.zip" if request.deliverable else "RawiBumi_numerical_export.zip"
        return Response(content, media_type="application/zip", headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "no-store",
        })

    # BETA1: a run longer than RAWIBUMI_SIMULATE_WAIT_SECONDS (unset: wait as long as it takes, as before) answers 202 with
    # a job to poll, so a proxy's per-request limit (about 100 s on Cloudflare) never cuts a run. Errors are re-raised
    # unchanged, so both routes answer exactly as the synchronous run would.
    simulate_wait = float(os.environ["RAWIBUMI_SIMULATE_WAIT_SECONDS"]) if os.environ.get("RAWIBUMI_SIMULATE_WAIT_SECONDS") else None
    jobs: dict[str, dict[str, Any]] = {}
    jobs_lock = threading.Lock()

    @app.post("/api/projects/{project_id}/simulate")
    def run_simulation(project_id: str, request: BrowserSimulationRequest | None = None) -> dict[str, Any]:  # the annotation keeps pydantic's JSON encoding (1e-8, not 1e-08): bytes as before
        config = request.electrical_shading_configuration.model_dump() if request and request.electrical_shading_configuration else None
        job_id = secrets.token_hex(16)  # not uuid4: runs that fix uuid4 for reproducible IDs must not see this draw
        job: dict[str, Any] = {"project_id": project_id, "done": threading.Event(), "result": None, "error": None, "started": time.time()}
        def work():
            try:
                job["result"] = study.run_study(project_id, config)
            except BaseException as exc:  # handed to the request that collects it, then translated there
                job["error"] = exc
            finally:
                job["done"].set()
        with jobs_lock:
            for stale in [k for k, v in jobs.items() if v["done"].is_set() and time.time() - v["started"] > 3600]:
                del jobs[stale]
            jobs[job_id] = job
        threading.Thread(target=work, name=f"simulate-{job_id}", daemon=True).start()
        if not job["done"].wait(simulate_wait):
            return JSONResponse(status_code=202, content={"job_id": job_id, "status": "running"})
        return _collect(job_id)

    def _collect(job_id: str) -> dict[str, Any]:
        with jobs_lock:
            job = jobs.pop(job_id)
        if job["error"] is not None:
            def reraise():
                raise job["error"]
            return _translate(reraise)
        return job["result"]

    @app.get("/api/projects/{project_id}/simulate/jobs/{job_id}")
    def simulation_job(project_id: str, job_id: str) -> dict[str, Any]:
        with jobs_lock:
            job = jobs.get(job_id)
        if job is None or job["project_id"] != project_id:
            raise HTTPException(status_code=404, detail={"code": "simulation_job_not_found", "message": "That run is no longer tracked; open Results to see saved runs."})
        if not job["done"].is_set():
            return JSONResponse(status_code=202, content={"job_id": job_id, "status": "running", "elapsed_seconds": round(time.time() - job["started"])})
        return _collect(job_id)

    @app.post("/api/projects/{project_id}/save")
    def save_project(project_id: str) -> dict[str, Any]:
        return _translate(lambda: service.save_project(project_id))

    # Decoded slashes in an invalid project id must reach id validation, while
    # existing nested DELETE routes retain precedence over this fallback.
    app.add_api_route("/api/projects/{project_id:path}", delete_project,
                      methods=["DELETE"], include_in_schema=False)

    dist = ROOT / "apps" / "web" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")

    return app


app = create_app()
