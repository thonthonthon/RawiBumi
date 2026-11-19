"""Canonical ProjectRevision -> SimulationRun orchestration for Phase 3.8E."""

from __future__ import annotations

from copy import deepcopy
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from math import isclose
from typing import Any, Mapping, Sequence, TYPE_CHECKING

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from components.pan.pvsyst_sdm import REQUIRED_PVSYST_PARAMETERS  # noqa: F401
from engine.inverter import (INVERTER_VOLTAGE_DEPENDENT, INVERTER_VOLTAGE_DEPENDENT_BOUNDED, ADJACENT_ENVELOPE_POLICY)
from engine.irradiance import (
    POA_PVSYST81_PEREZ,
    PerezCoefficientSet,
    SUPPORTED_DECOMPOSITION_MODELS,
    SUPPORTED_TRANSPOSITION_MODELS,
)
from engine.module import MODULE_PVSYST_SDM
from engine.optical import IAM_NONE, IAM_TABULATED, SUPPORTED_IAM_MODELS
from engine.solar import SOLAR_POSITION_NREL_SPA, solar_position_from_weather
from engine.thermal import SUPPORTED_THERMAL_MODELS
from geometry.shading import (
    BEAM_SOLVER_ID,
    SKY_VISIBILITY_SOLVER_ID,
    GROUND_VISIBILITY_SOLVER_ID,
    ShadingContractError,
    SkyDomeResolution,
    SkyVisibilityError,
    GroundDomeResolution,
    GroundVisibilityError,
    assert_geometry_aware_shading_configuration,
    normalize_product_namespace_identifier,
    compile_shading_geometry,
)
from weather.core import CanonicalWeather
from weather.validation import run_solar_aware_weather_qc

from .artifacts import (
    build_standard_timeseries,
    build_summary_result,
    canonical_object_sha256,
    persist_parquet_result,
    persist_receiver_factor_result,
    ReceiverFactorParquetSink,
    persist_run_package,
    weather_series_logical_sha256,
)
from .geometry_aware import (
    BEAM_VISIBILITY_AGGREGATION_METHOD_ID,
    DIFFUSE_VISIBILITY_AGGREGATION_METHOD_ID,
    GROUND_VISIBILITY_AGGREGATION_METHOD_ID,
    run_beam_shaded_fixed_tilt,
    run_beam_sky_shaded_fixed_tilt,
    run_beam_sky_ground_shaded_fixed_tilt,
)
from .annual_shading import build_annual_shading_result
from .models import resolve_simulation_models
from .temporal import prepare_temporal_execution
from .execution_groups import build_simulation_execution_plan
from .unshaded import (
    UnshadedFixedTiltConfiguration,
    UnshadedFixedTiltSimulationResult,
    run_unshaded_fixed_tilt,
)
from .detailed_inputs import FrozenDetailedSelectionSnapshot


if TYPE_CHECKING:
    from .multi_group import MultiGroupSimulationResult


ROOT = Path(__file__).resolve().parents[2]

RECEIVER_FACTOR_STREAMING_ROW_THRESHOLD = 250_000
RECEIVER_FACTOR_STREAMING_CHUNK_ROWS = 8192



@dataclass(frozen=True)
class CanonicalRevisionStore:
    """Resolved immutable revisions available to the synchronous Phase-3.8E worker."""

    scene_revisions: Mapping[str, dict[str, Any]]
    electrical_revisions: Mapping[str, dict[str, Any]]
    weather_revisions: Mapping[str, CanonicalWeather]
    component_revisions: Mapping[str, dict[str, Any]]
    detailed_electrical_inputs: FrozenDetailedSelectionSnapshot | None = None


@dataclass(frozen=True)
class CanonicalSimulationExecutionResult:
    """Canonical run package plus optional in-memory backend result."""

    simulation_run: dict[str, Any]
    summary_result: dict[str, Any] | None
    standard_timeseries: Any | None
    backend_result: UnshadedFixedTiltSimulationResult | MultiGroupSimulationResult | None
    artifact_directory: Path
    detailed_backend_result: Any | None = None
    detailed_attribution_result: Any | None = None


def _timestamp(value: datetime | str | None) -> str:
    if value is None:
        resolved = datetime.now(timezone.utc)
    elif isinstance(value, str):
        resolved = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        resolved = value
    if resolved.tzinfo is None:
        raise ValueError("executed_at must be timezone-aware")
    return resolved.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _schema(filename: str) -> dict[str, Any]:
    import json

    path = ROOT / filename if "/" in filename else ROOT / "schemas" / filename
    return json.loads(path.read_text(encoding="utf-8"))


def _schema_findings(
    value: Any,
    *,
    filename: str,
    entity_id: str,
    project_revision_id: str,
    generated_at: str,
    finding_prefix: str,
) -> list[dict[str, Any]]:
    validator = Draft202012Validator(
        _schema(filename),
        registry=_output_registry(),
    )
    findings: list[dict[str, Any]] = []
    for index, error in enumerate(
        sorted(validator.iter_errors(value), key=lambda item: list(item.absolute_path)),
        start=1,
    ):
        path = ".".join(str(item) for item in error.absolute_path) or "$"
        findings.append(
            {
                "schema_name": "ValidationFinding",
                "schema_version": "0.1",
                "finding_id": f"{finding_prefix}:{index:03d}",
                "project_revision_id": project_revision_id,
                "entity_id": entity_id,
                "rule_id": "CANONICAL_SCHEMA_INVALID",
                "severity": "blocking_error",
                "category": "canonical_schema",
                "message": f"{filename} validation failed at {path}: {error.message}",
                "unit": None,
                "context": {
                    "schema_file": filename,
                    "instance_path": path,
                    "validator": error.validator,
                },
                "generated_at": generated_at,
            }
        )
    return findings


def _output_registry() -> Registry:
    """Registry for cross-domain and subsystem-owned canonical schemas."""
    import json

    registry = Registry()
    schema_directories = (
        ROOT / "schemas",
        ROOT / "components/schema",
        ROOT / "weather/schema",
        ROOT / "geometry/scene",
        ROOT / "geometry/coordinates",
        ROOT / "geometry/shading",
        ROOT / "electrical/schema",
        ROOT / "shading/electrical",
    )
    for directory in schema_directories:
        for path in directory.glob("*.schema.json"):
            schema = json.loads(path.read_text(encoding="utf-8"))
            if "$id" in schema:
                registry = registry.with_resource(
                    schema["$id"],
                    Resource.from_contents(schema),
                )
    return registry


def _assert_output_schema(value: Any, filename: str) -> None:
    Draft202012Validator(
        _schema(filename),
        registry=_output_registry(),
    ).validate(value)


def _finding(
    *,
    run_id: str,
    ordinal: int,
    project_revision_id: str,
    entity_id: str,
    rule_id: str,
    severity: str,
    category: str,
    message: str,
    generated_at: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_name": "ValidationFinding",
        "schema_version": "0.1",
        "finding_id": f"{run_id}:finding:{ordinal:03d}",
        "project_revision_id": project_revision_id,
        "entity_id": entity_id,
        "rule_id": rule_id,
        "severity": severity,
        "category": category,
        "message": message,
        "unit": None,
        "context": context or {},
        "generated_at": generated_at,
    }


def _counts(findings: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "warning_count": sum(item["severity"] == "warning" for item in findings),
        "error_count": sum(item["severity"] == "error" for item in findings),
        "blocking_error_count": sum(
            item["severity"] == "blocking_error" for item in findings
        ),
    }


def _warning_summary(
    findings: list[dict[str, Any]],
    assumptions: list[dict[str, Any]],
    model_resolution: dict[str, Any] | None,
) -> dict[str, int]:
    result = _counts(findings)
    result["warning_count"] += sum(
        item.get("severity") == "warning" for item in assumptions
    )
    if model_resolution is not None:
        result["warning_count"] += len(model_resolution.get("warnings") or [])
    return result


def _has_blocker(findings: list[dict[str, Any]]) -> bool:
    return any(item["severity"] == "blocking_error" for item in findings)


def _add(
    findings: list[dict[str, Any]],
    *,
    run_id: str,
    project_revision_id: str,
    entity_id: str,
    rule_id: str,
    severity: str,
    category: str,
    message: str,
    generated_at: str,
    context: dict[str, Any] | None = None,
) -> None:
    findings.append(
        _finding(
            run_id=run_id,
            ordinal=len(findings) + 1,
            project_revision_id=project_revision_id,
            entity_id=entity_id,
            rule_id=rule_id,
            severity=severity,
            category=category,
            message=message,
            generated_at=generated_at,
            context=context,
        )
    )


def _select_weather_period(
    weather: CanonicalWeather,
    simulation_configuration: dict[str, Any],
) -> CanonicalWeather:
    start = simulation_configuration.get("start_time")
    end = simulation_configuration.get("end_time")
    if start is None and end is None:
        return weather.copy()

    result = weather.copy()
    index = result.series.index
    if start is not None:
        start_ts = __import__("pandas").Timestamp(start)
        if start_ts.tzinfo is None:
            raise ValueError("simulation start_time must be timezone-aware")
        if start_ts not in index:
            raise ValueError(
                "simulation start_time must align with a canonical weather interval start"
            )
    else:
        start_ts = index[0]

    if end is not None:
        end_ts = __import__("pandas").Timestamp(end)
        if end_ts.tzinfo is None:
            raise ValueError("simulation end_time must be timezone-aware")
        dataset_end = __import__("pandas").Timestamp(result.dataset["end_time"])
        if end_ts != dataset_end and end_ts not in index:
            raise ValueError(
                "simulation end_time must align with a canonical weather interval boundary"
            )
    else:
        end_ts = __import__("pandas").Timestamp(result.dataset["end_time"])

    if end_ts <= start_ts:
        raise ValueError("simulation end_time must be after start_time")

    mask = (index >= start_ts) & (index < end_ts)
    result.series = result.series.loc[mask].copy()
    if result.series.empty:
        raise ValueError("simulation period selects no weather intervals")
    result.dataset["start_time"] = result.series.index[0].isoformat()
    result.dataset["end_time"] = end_ts.isoformat()
    return result


def _revision_inputs(
    project_revision: dict[str, Any],
    simulation_configuration: dict[str, Any],
    store: CanonicalRevisionStore,
    *,
    run_id: str,
    generated_at: str,
    findings: list[dict[str, Any]],
) -> tuple[
    dict[str, Any] | None,
    dict[str, Any] | None,
    CanonicalWeather | None,
]:
    project_revision_id = str(
        project_revision.get("project_revision_id") or "unresolved-project-revision"
    )
    config_project_revision_id = simulation_configuration.get("project_revision_id")
    if config_project_revision_id != project_revision.get("project_revision_id"):
        _add(
            findings,
            run_id=run_id,
            project_revision_id=project_revision_id,
            entity_id=str(
                simulation_configuration.get("simulation_configuration_id")
                or "simulation-configuration"
            ),
            rule_id="SIMULATION_PROJECT_REVISION_MISMATCH",
            severity="blocking_error",
            category="revision_resolution",
            message=(
                "SimulationConfiguration.project_revision_id does not match the "
                "supplied ProjectRevision."
            ),
            generated_at=generated_at,
        )

    scene_id = project_revision.get("scene_revision_id")
    electrical_id = project_revision.get("electrical_revision_id")
    weather_id = simulation_configuration.get("weather_dataset_revision_id")
    project_weather_id = project_revision.get("weather_dataset_revision_id")

    if project_weather_id is not None and weather_id != project_weather_id:
        _add(
            findings,
            run_id=run_id,
            project_revision_id=project_revision_id,
            entity_id=str(weather_id or "weather"),
            rule_id="SIMULATION_WEATHER_REVISION_MISMATCH",
            severity="blocking_error",
            category="revision_resolution",
            message=(
                "SimulationConfiguration weather revision differs from the "
                "weather revision pinned by ProjectRevision."
            ),
            generated_at=generated_at,
            context={
                "project_weather_revision_id": project_weather_id,
                "configuration_weather_revision_id": weather_id,
            },
        )

    scene = store.scene_revisions.get(str(scene_id)) if scene_id else None
    electrical = (
        store.electrical_revisions.get(str(electrical_id))
        if electrical_id
        else None
    )
    weather = store.weather_revisions.get(str(weather_id)) if weather_id else None

    for kind, revision_id, resolved in (
        ("scene", scene_id, scene),
        ("electrical", electrical_id, electrical),
        ("weather", weather_id, weather),
    ):
        if resolved is None:
            _add(
                findings,
                run_id=run_id,
                project_revision_id=project_revision_id,
                entity_id=str(revision_id or kind),
                rule_id="SIMULATION_REQUIRED_REVISION_NOT_FOUND",
                severity="blocking_error",
                category="revision_resolution",
                message=f"Required {kind} revision is not available in the revision store.",
                generated_at=generated_at,
                context={"revision_type": kind, "revision_id": revision_id},
            )

    if scene is not None and scene.get("revision_id") != scene_id:
        _add(
            findings,
            run_id=run_id,
            project_revision_id=project_revision_id,
            entity_id=str(scene_id),
            rule_id="SIMULATION_SCENE_REVISION_IDENTITY_MISMATCH",
            severity="blocking_error",
            category="revision_resolution",
            message="Resolved Scene.revision_id does not match ProjectRevision.",
            generated_at=generated_at,
        )
    if (
        electrical is not None
        and electrical.get("electrical_revision_id") != electrical_id
    ):
        _add(
            findings,
            run_id=run_id,
            project_revision_id=project_revision_id,
            entity_id=str(electrical_id),
            rule_id="SIMULATION_ELECTRICAL_REVISION_IDENTITY_MISMATCH",
            severity="blocking_error",
            category="revision_resolution",
            message=(
                "Resolved ElectricalDesignRevision identity does not match "
                "ProjectRevision."
            ),
            generated_at=generated_at,
        )
    if weather is not None and weather.dataset.get("revision_id") != weather_id:
        _add(
            findings,
            run_id=run_id,
            project_revision_id=project_revision_id,
            entity_id=str(weather_id),
            rule_id="SIMULATION_WEATHER_REVISION_IDENTITY_MISMATCH",
            severity="blocking_error",
            category="revision_resolution",
            message="Resolved WeatherDataset revision identity does not match configuration.",
            generated_at=generated_at,
        )

    return scene, electrical, weather


def _resolve_shading_mode(simulation_configuration, *, run_id, project_revision_id,
                          generated_at, findings):
    shading = simulation_configuration.get("shading_configuration") or {}
    beam_method = normalize_product_namespace_identifier(shading.get("beam_method"))
    diffuse_method = normalize_product_namespace_identifier(shading.get("diffuse_method"))
    albedo_method = normalize_product_namespace_identifier(shading.get("albedo_method"))
    shading_execution_mode = "unshaded"

    geometry_diffuse_methods = {"none", SKY_VISIBILITY_SOLVER_ID}
    if beam_method == "none" and diffuse_method == "none":
        # Legacy/unshaded configurations may use albedo_method to describe the
        # numerical albedo source. Ground-visibility geometry is inactive here.
        shading_execution_mode = "unshaded"
    elif (
        beam_method == BEAM_SOLVER_ID
        and diffuse_method in geometry_diffuse_methods
    ):
        if diffuse_method == "none":
            shading_execution_mode = "beam_only_geometry"
        elif albedo_method == GROUND_VISIBILITY_SOLVER_ID:
            shading_execution_mode = "beam_sky_ground_geometry"
        else:
            shading_execution_mode = "beam_sky_geometry"

        try:
            assert_geometry_aware_shading_configuration(shading)
        except ShadingContractError as exc:
            if shading_execution_mode == "beam_only_geometry":
                rule_id = "SIMULATION_SCOPE_BEAM_SHADING_CONFIGURATION_INVALID"
            elif shading_execution_mode == "beam_sky_geometry":
                rule_id = "SIMULATION_SCOPE_SKY_SHADING_CONFIGURATION_INVALID"
            else:
                rule_id = "SIMULATION_SCOPE_GROUND_SHADING_CONFIGURATION_INVALID"
            _add(
                findings,
                run_id=run_id,
                project_revision_id=project_revision_id,
                entity_id=str(
                    simulation_configuration.get("simulation_configuration_id")
                ),
                rule_id=rule_id,
                severity="blocking_error",
                category="execution_scope",
                message=str(exc),
                generated_at=generated_at,
            )

        expected_albedo_methods = (
            {None, "none"}
            if shading_execution_mode != "beam_sky_ground_geometry"
            else {GROUND_VISIBILITY_SOLVER_ID}
        )
        if albedo_method not in expected_albedo_methods:
            _add(
                findings,
                run_id=run_id,
                project_revision_id=project_revision_id,
                entity_id=str(
                    simulation_configuration.get("simulation_configuration_id")
                ),
                rule_id="SIMULATION_SCOPE_GROUND_OBSTRUCTION_METHOD_INVALID",
                severity="blocking_error",
                category="execution_scope",
                message=(
                    "Beam-only and beam+sky modes require ground obstruction "
                    "disabled. Phase 5.7 beam+sky+ground execution requires "
                    f"albedo_method={GROUND_VISIBILITY_SOLVER_ID!r}."
                ),
                generated_at=generated_at,
                context={"albedo_method": albedo_method},
            )

        if (
            albedo_method == GROUND_VISIBILITY_SOLVER_ID
            and diffuse_method != SKY_VISIBILITY_SOLVER_ID
        ):
            _add(
                findings,
                run_id=run_id,
                project_revision_id=project_revision_id,
                entity_id=str(
                    simulation_configuration.get("simulation_configuration_id")
                ),
                rule_id="SIMULATION_SCOPE_GROUND_REQUIRES_SKY_GEOMETRY",
                severity="blocking_error",
                category="execution_scope",
                message=(
                    "Phase 5.7 ground obstruction is integrated on the complete "
                    "beam+sky geometry path; diffuse_method must select the "
                    "Phase-5.6 weighted sky solver."
                ),
                generated_at=generated_at,
            )

        if shading.get("receiver_granularity") != "module":
            if shading_execution_mode == "beam_only_geometry":
                rule_id = "SIMULATION_SCOPE_BEAM_REQUIRES_MODULE_RECEIVERS"
            elif shading_execution_mode == "beam_sky_geometry":
                rule_id = "SIMULATION_SCOPE_SKY_REQUIRES_MODULE_RECEIVERS"
            else:
                rule_id = "SIMULATION_SCOPE_GROUND_REQUIRES_MODULE_RECEIVERS"
            _add(
                findings,
                run_id=run_id,
                project_revision_id=project_revision_id,
                entity_id=str(
                    simulation_configuration.get("simulation_configuration_id")
                ),
                rule_id=rule_id,
                severity="blocking_error",
                category="execution_scope",
                message=(
                    "The current homogeneous electrical aggregation requires "
                    "receiver_granularity='module'."
                ),
                generated_at=generated_at,
            )

        if shading.get("sun_position_resolution_seconds") is not None:
            _add(
                findings,
                run_id=run_id,
                project_revision_id=project_revision_id,
                entity_id=str(
                    simulation_configuration.get("simulation_configuration_id")
                ),
                rule_id="SIMULATION_SCOPE_SUN_POSITION_RESOLUTION_NOT_EXECUTABLE",
                severity="blocking_error",
                category="execution_scope",
                message=(
                    "The Phase-5.8 exact annual shading path evaluates every "
                    "canonical simulation solar-evaluation timestamp. Additional "
                    "sun-position temporal coarsening is not implemented; "
                    "sun_position_resolution_seconds must be null."
                ),
                generated_at=generated_at,
                context={
                    "sun_position_resolution_seconds": shading.get(
                        "sun_position_resolution_seconds"
                    ),
                    "sampling_policy": (
                        "canonical_simulation_solar_evaluation_timestamps"
                    ),
                },
            )

        cache_mode = (shading.get("cache_policy") or {}).get("mode")
        if cache_mode not in {"none", "exact"}:
            _add(
                findings,
                run_id=run_id,
                project_revision_id=project_revision_id,
                entity_id=str(
                    simulation_configuration.get("simulation_configuration_id")
                ),
                rule_id="SIMULATION_SCOPE_SHADING_CACHE_MODE_NOT_EXECUTABLE",
                severity="blocking_error",
                category="execution_scope",
                message=(
                    "Phase 5.7 supports only exact/no-cache geometry execution; "
                    "angular-bin acceleration remains deferred."
                ),
                generated_at=generated_at,
            )

        resolution = shading.get("geometric_resolution") or {}
        if any(
            resolution.get(field, 1) != 1
            for field in ("receiver_subdivision_u", "receiver_subdivision_v")
        ) or "occluder_chord_tolerance_m" in resolution:
            _add(
                findings,
                run_id=run_id,
                project_revision_id=project_revision_id,
                entity_id=str(
                    simulation_configuration.get("simulation_configuration_id")
                ),
                rule_id="SIMULATION_SCOPE_SHADING_RESOLUTION_NOT_EXECUTABLE",
                severity="blocking_error",
                category="execution_scope",
                message=(
                    "The current reference geometry kernels execute full compiled "
                    "module polygons without receiver subdivision or chord-tolerance "
                    "approximation."
                ),
                generated_at=generated_at,
            )

        if shading.get("model_options"):
            _add(
                findings,
                run_id=run_id,
                project_revision_id=project_revision_id,
                entity_id=str(
                    simulation_configuration.get("simulation_configuration_id")
                ),
                rule_id="SIMULATION_SCOPE_SHADING_MODEL_OPTIONS_NOT_EXECUTABLE",
                severity="blocking_error",
                category="execution_scope",
                message=(
                    "Phase 5.7 reference geometry execution accepts no hidden "
                    "model_options."
                ),
                generated_at=generated_at,
            )

        if shading_execution_mode in {
            "beam_sky_geometry",
            "beam_sky_ground_geometry",
        }:
            sky_resolution = shading.get("sky_dome_resolution")
            if not isinstance(sky_resolution, Mapping):
                _add(
                    findings,
                    run_id=run_id,
                    project_revision_id=project_revision_id,
                    entity_id=str(
                        simulation_configuration.get("simulation_configuration_id")
                    ),
                    rule_id="SIMULATION_SCOPE_SKY_DOME_CONFIGURATION_INVALID",
                    severity="blocking_error",
                    category="execution_scope",
                    message=(
                        "Diffuse sky execution requires an explicit "
                        "sky_dome_resolution object."
                    ),
                    generated_at=generated_at,
                )
            else:
                try:
                    SkyDomeResolution.from_mapping(sky_resolution)
                except SkyVisibilityError as exc:
                    _add(
                        findings,
                        run_id=run_id,
                        project_revision_id=project_revision_id,
                        entity_id=str(
                            simulation_configuration.get(
                                "simulation_configuration_id"
                            )
                        ),
                        rule_id="SIMULATION_SCOPE_SKY_DOME_CONFIGURATION_INVALID",
                        severity="blocking_error",
                        category="execution_scope",
                        message=str(exc),
                        generated_at=generated_at,
                    )

        if shading_execution_mode == "beam_sky_ground_geometry":
            ground_resolution = shading.get("ground_dome_resolution")
            if not isinstance(ground_resolution, Mapping):
                _add(
                    findings,
                    run_id=run_id,
                    project_revision_id=project_revision_id,
                    entity_id=str(
                        simulation_configuration.get("simulation_configuration_id")
                    ),
                    rule_id="SIMULATION_SCOPE_GROUND_DOME_CONFIGURATION_INVALID",
                    severity="blocking_error",
                    category="execution_scope",
                    message=(
                        "Phase 5.7 ground execution requires an explicit "
                        "ground_dome_resolution object."
                    ),
                    generated_at=generated_at,
                )
            else:
                try:
                    GroundDomeResolution.from_mapping(ground_resolution)
                except GroundVisibilityError as exc:
                    _add(
                        findings,
                        run_id=run_id,
                        project_revision_id=project_revision_id,
                        entity_id=str(
                            simulation_configuration.get(
                                "simulation_configuration_id"
                            )
                        ),
                        rule_id="SIMULATION_SCOPE_GROUND_DOME_CONFIGURATION_INVALID",
                        severity="blocking_error",
                        category="execution_scope",
                        message=str(exc),
                        generated_at=generated_at,
                    )
    else:
        _add(
            findings,
            run_id=run_id,
            project_revision_id=project_revision_id,
            entity_id=str(
                simulation_configuration.get("simulation_configuration_id")
            ),
            rule_id="SIMULATION_SCOPE_UNSHADED_ONLY",
            severity="blocking_error",
            category="execution_scope",
            message=(
                "This shading configuration is not executable by the current "
                "runtime. Historical/external shading references are preserved "
                "as references and are not silently reinterpreted."
            ),
            generated_at=generated_at,
            context={
                "beam_method": beam_method,
                "diffuse_method": diffuse_method,
                "albedo_method": albedo_method,
                "supported_beam_method": BEAM_SOLVER_ID,
                "supported_diffuse_methods": [
                    "none",
                    SKY_VISIBILITY_SOLVER_ID,
                ],
                "supported_ground_method": GROUND_VISIBILITY_SOLVER_ID,
            },
        )

    return shading_execution_mode


def _resolve_topology(
    scene: dict[str, Any],
    electrical: dict[str, Any],
    store: CanonicalRevisionStore,
    simulation_configuration: dict[str, Any],
    *,
    run_id: str,
    project_revision_id: str,
    generated_at: str,
    findings: list[dict[str, Any]],
    detailed: bool = False,
) -> dict[str, Any] | None:
    enabled_inverters = [
        item for item in electrical.get("inverter_instances", [])
        if item.get("enabled") is True
    ]
    if len(enabled_inverters) != 1:
        _add(
            findings,
            run_id=run_id,
            project_revision_id=project_revision_id,
            entity_id=str(electrical.get("electrical_revision_id")),
            rule_id="SIMULATION_SCOPE_REQUIRES_SINGLE_INVERTER",
            severity="blocking_error",
            category="execution_scope",
            message=(
                "The current numerical adapter requires exactly one enabled "
                "inverter instance."
            ),
            generated_at=generated_at,
            context={"enabled_inverter_count": len(enabled_inverters)},
        )
        return None

    inverter_instance = enabled_inverters[0]
    inverter_revision_id = inverter_instance.get("inverter_definition_revision_id")
    inverter = store.component_revisions.get(str(inverter_revision_id))
    if inverter is None:
        _add(
            findings,
            run_id=run_id,
            project_revision_id=project_revision_id,
            entity_id=str(inverter_revision_id),
            rule_id="SIMULATION_COMPONENT_REVISION_NOT_FOUND",
            severity="blocking_error",
            category="revision_resolution",
            message="Inverter component revision is not available in the revision store.",
            generated_at=generated_at,
        )
        return None

    enabled_strings = [
        item for item in electrical.get("strings", [])
        if item.get("enabled") is True
    ]
    if not enabled_strings:
        _add(
            findings,
            run_id=run_id,
            project_revision_id=project_revision_id,
            entity_id=str(electrical.get("electrical_revision_id")),
            rule_id="SIMULATION_NO_ENABLED_STRINGS",
            severity="blocking_error",
            category="electrical_topology",
            message="No enabled StringCircuit objects are available for simulation.",
            generated_at=generated_at,
        )
        return None
    if any(item.get("polarity") != "normal" for item in enabled_strings):
        _add(
            findings,
            run_id=run_id,
            project_revision_id=project_revision_id,
            entity_id=str(electrical.get("electrical_revision_id")),
            rule_id="SIMULATION_UNSUPPORTED_STRING_POLARITY",
            severity="blocking_error",
            category="execution_scope",
            message="The current numerical runtime supports only normal string polarity.",
            generated_at=generated_at,
        )

    shading_execution_mode = _resolve_shading_mode(
        simulation_configuration, run_id=run_id, project_revision_id=project_revision_id,
        generated_at=generated_at, findings=findings,
    )

    enabled_mppts = [
        item for item in electrical.get("mppt_instances", [])
        if item.get("enabled") is True
        and item.get("inverter_instance_id")
        == inverter_instance.get("inverter_instance_id")
    ]
    mppt_by_id = {item["mppt_instance_id"]: item for item in enabled_mppts}
    string_ids = {str(item["string_id"]) for item in enabled_strings}
    assignments: dict[int, tuple[str, ...]] = {}

    for mppt in enabled_mppts:
        connected = tuple(
            str(value) for value in mppt.get("connected_string_ids", [])
        )
        if any(value not in string_ids for value in connected):
            _add(
                findings,
                run_id=run_id,
                project_revision_id=project_revision_id,
                entity_id=str(mppt["mppt_instance_id"]),
                rule_id="SIMULATION_MPPT_UNKNOWN_STRING",
                severity="blocking_error",
                category="electrical_topology",
                message="MPPT references a string that is not enabled in this revision.",
                generated_at=generated_at,
            )
        assignments[int(mppt["index"])] = connected

    for string in enabled_strings:
        target = string.get("target_mppt_instance_id")
        mppt = mppt_by_id.get(target)
        if mppt is None or string["string_id"] not in (
            mppt.get("connected_string_ids") or []
        ):
            _add(
                findings,
                run_id=run_id,
                project_revision_id=project_revision_id,
                entity_id=str(string["string_id"]),
                rule_id="SIMULATION_STRING_MPPT_ASSIGNMENT_INCONSISTENT",
                severity="blocking_error",
                category="electrical_topology",
                message=(
                    "String target MPPT and MPPT connected_string_ids do not reconcile."
                ),
                generated_at=generated_at,
            )

    if _has_blocker(findings):
        return None

    compiled_shading_geometry = compile_shading_geometry(scene)
    execution_plan = build_simulation_execution_plan(
        scene,
        electrical,
        numerical_options=(
            simulation_configuration.get("numerical_options") or {}
        ),
        compiled_shading_geometry=compiled_shading_geometry,
        detailed=detailed,
    )
    execution_class = execution_plan["execution_class"]
    if shading_execution_mode in {
        "beam_only_geometry",
        "beam_sky_geometry",
        "beam_sky_ground_geometry",
    }:
        missing_receiver_module_ids = sorted(
            {
                str(module_id)
                for group in execution_plan.get("groups", [])
                for module_id in group.get("missing_receiver_module_ids", [])
            }
        )
        if missing_receiver_module_ids:
            _add(
                findings,
                run_id=run_id,
                project_revision_id=project_revision_id,
                entity_id=str(electrical.get("electrical_revision_id")),
                rule_id="SIMULATION_SCOPE_BEAM_RECEIVERS_UNRESOLVED",
                severity="blocking_error",
                category="execution_scope",
                message=(
                    "Geometry-aware execution requires a compiled module "
                    "receiver for every active module."
                ),
                generated_at=generated_at,
                context={
                    "missing_receiver_module_ids": missing_receiver_module_ids,
                },
            )
    if execution_class == "electrically_coupled_heterogeneous":
        _add(
            findings,
            run_id=run_id,
            project_revision_id=project_revision_id,
            entity_id=str(electrical.get("electrical_revision_id")),
            rule_id="SIMULATION_SCOPE_HETEROGENEOUS_MPPT_EXECUTION_GROUPS",
            severity="blocking_error",
            category="execution_scope",
            message=(
                "Canonical topology resolves to multiple execution groups on "
                "the same MPPT. Their heterogeneous IV interaction is outside "
                "the Phase-5 geometry-only electrical boundary."
            ),
            generated_at=generated_at,
            context={
                "execution_plan_id": execution_plan["execution_plan_id"],
                "execution_plan_payload_sha256": execution_plan["execution_plan_payload_sha256"],
                "execution_class": execution_class,
                "group_count": execution_plan["group_count"],
                "heterogeneous_mppt_instance_ids": execution_plan[
                    "heterogeneous_mppt_instance_ids"
                ],
                "plan_findings": execution_plan["findings"],
            },
        )
    elif execution_class == "invalid":
        _add(
            findings,
            run_id=run_id,
            project_revision_id=project_revision_id,
            entity_id=str(electrical.get("electrical_revision_id")),
            rule_id="SIMULATION_EXECUTION_GROUP_PLAN_INVALID",
            severity="blocking_error",
            category="execution_scope",
            message=(
                "Canonical Scene/Electrical topology could not be reduced to "
                "valid homogeneous execution groups."
            ),
            generated_at=generated_at,
            context={
                "execution_plan_id": execution_plan["execution_plan_id"],
                "execution_plan_payload_sha256": execution_plan["execution_plan_payload_sha256"],
                "plan_findings": execution_plan["findings"],
            },
        )
    elif execution_class == "separable_multi_group":
        _add(
            findings,
            run_id=run_id,
            project_revision_id=project_revision_id,
            entity_id=str(electrical.get("electrical_revision_id")),
            rule_id="SIMULATION_SCOPE_MULTIPLE_EXECUTION_GROUPS_NOT_EXECUTABLE",
            severity="blocking_error",
            category="execution_scope",
            message=(
                "Canonical topology contains multiple electrically separable "
                "execution groups. Phase 5.2 preserves those groups instead of "
                "flattening them, but the legacy numerical backend still "
                "executes one homogeneous group per run."
            ),
            generated_at=generated_at,
            context={
                "execution_plan_id": execution_plan["execution_plan_id"],
                "execution_plan_payload_sha256": execution_plan["execution_plan_payload_sha256"],
                "execution_class": execution_class,
                "group_count": execution_plan["group_count"],
                "groups": [
                    {
                        "execution_group_id": group["execution_group_id"],
                        "string_ids": group["string_ids"],
                        "mppt_instance_ids": group["mppt_instance_ids"],
                        "surface_tilt_deg": group["surface_tilt_deg"],
                        "surface_azimuth_deg": group["surface_azimuth_deg"],
                        "albedo": group["albedo"],
                        "module_revision_id": group["module_revision_id"],
                        "modules_in_series": group["modules_in_series"],
                    }
                    for group in execution_plan["groups"]
                ],
            },
        )

    if _has_blocker(findings):
        return None

    if (
        execution_plan["execution_class"] != "homogeneous_single_group"
        or execution_plan["group_count"] != 1
    ):
        raise RuntimeError(
            "execution-group classification invariant violated before legacy "
            "homogeneous worker adaptation"
        )

    group = execution_plan["groups"][0]
    module_revision_id = str(group["module_revision_id"])
    module = store.component_revisions.get(module_revision_id)
    if module is None:
        _add(
            findings,
            run_id=run_id,
            project_revision_id=project_revision_id,
            entity_id=module_revision_id,
            rule_id="SIMULATION_COMPONENT_REVISION_NOT_FOUND",
            severity="blocking_error",
            category="revision_resolution",
            message="Module component revision is not available in the revision store.",
            generated_at=generated_at,
        )
        return None

    albedo_sources = tuple(group["albedo_sources"])
    albedo_source = (
        albedo_sources[0]
        if len(albedo_sources) == 1
        else "execution_group.mixed_provenance_equal_value"
    )

    circuit_resolution = None
    from engine.losses.settings import resolve_circuit_loss_settings
    try:
        stored_losses = simulation_configuration.get("numerical_options", {}).get("loss_settings")
        if stored_losses is not None:
            circuit_resolution = resolve_circuit_loss_settings(stored_losses, scene, electrical,
                store.component_revisions, module_quality_override=simulation_configuration.get("numerical_options", {}).get("module_overrides", {}).get("module_quality_loss_fraction"), detailed=detailed)
    except (ValueError, KeyError, TypeError) as exc:
        _add(findings, run_id=run_id, project_revision_id=project_revision_id,
            entity_id=str(electrical["electrical_revision_id"]), rule_id="LOSS_SETTINGS_INVALID",
            severity="blocking_error", category="loss_settings", message=str(exc), generated_at=generated_at)
        return None
    return {
        "circuit_loss_resolution": circuit_resolution,
        "inverter_instance_id": group["inverter_instance_id"],
        "module": module,
        "module_revision_id": module_revision_id,
        "inverter": inverter,
        "inverter_revision_id": str(inverter_revision_id),
        "surface_tilt_deg": float(group["surface_tilt_deg"]),
        "surface_azimuth_deg": float(group["surface_azimuth_deg"]),
        "albedo": float(group["albedo"]),
        "albedo_source": albedo_source,
        "albedo_sources": albedo_sources,
        "modules_in_series": int(group["modules_in_series"]),
        "string_ids": tuple(group["string_ids"]),
        "mppt_assignments": assignments,
        "execution_group_plan": execution_plan,
        "compiled_shading_geometry": compiled_shading_geometry,
        "shading_execution_mode": shading_execution_mode,
    }

def _runtime_assumption(
    assumption_id: str,
    *,
    kind: str,
    scope: str,
    statement: str,
    basis: str,
    severity: str = "info",
    source_paths: tuple[str, ...] = (),
    affects: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "schema_name": "SimulationAssumption",
        "schema_version": "0.1",
        "assumption_id": assumption_id,
        "kind": kind,
        "scope": scope,
        "statement": statement,
        "basis": basis,
        "severity": severity,
        "source_paths": list(source_paths),
        "affects": list(affects),
    }


def _build_runtime_config(
    simulation_configuration: dict[str, Any],
    topology: dict[str, Any],
    model_resolution: dict[str, Any],
    *,
    run_id: str,
    project_revision_id: str,
    generated_at: str,
    findings: list[dict[str, Any]],
    assumptions: list[dict[str, Any]],
) -> UnshadedFixedTiltConfiguration | None:
    selections = simulation_configuration.get("model_selections") or {}
    optics_settings = None
    optics_iam = None
    stored_optics = simulation_configuration.get("numerical_options", {}).get("optics_thermal_settings")
    if stored_optics is not None:
        from .optics_thermal import resolve_optics_thermal_settings, configure_optics_thermal, resolve_iam
        optics_settings = resolve_optics_thermal_settings(stored_optics)
        expected = deepcopy(simulation_configuration)
        configure_optics_thermal(expected, stored_optics)
        if any(selections.get(k) != expected["model_selections"][k] for k in ("transposition", "iam", "temperature")):
            raise ValueError("Optics/thermal settings conflict with explicit model selections")
        if simulation_configuration.get("simulation_timestep_seconds") != 3600:
            raise ValueError("Optics/thermal settings require the supported hourly timestep")
        optics_iam = resolve_iam(optics_settings, topology["module"])

    solar_model = selections.get("solar_position")
    if solar_model != SOLAR_POSITION_NREL_SPA:
        _add(
            findings,
            run_id=run_id,
            project_revision_id=project_revision_id,
            entity_id=str(simulation_configuration["simulation_configuration_id"]),
            rule_id="SIMULATION_SOLAR_MODEL_NOT_EXECUTABLE",
            severity="blocking_error",
            category="model_resolution",
            message=(
                "Current Phase-3 numerical runner supports only the NREL SPA "
                "solar-position model."
            ),
            generated_at=generated_at,
            context={
                "requested_model_id": solar_model,
                "supported_model_id": SOLAR_POSITION_NREL_SPA,
            },
        )

    poa_model = selections.get("transposition")
    if poa_model not in SUPPORTED_TRANSPOSITION_MODELS:
        _add(
            findings,
            run_id=run_id,
            project_revision_id=project_revision_id,
            entity_id=str(simulation_configuration["simulation_configuration_id"]),
            rule_id="SIMULATION_TRANSPOSITION_MODEL_NOT_EXECUTABLE",
            severity="blocking_error",
            category="model_resolution",
            message="Requested transposition model is not executable by Phase 3.",
            generated_at=generated_at,
            context={"requested_model_id": poa_model},
        )

    thermal_model = selections.get("temperature")
    if thermal_model not in SUPPORTED_THERMAL_MODELS:
        _add(
            findings,
            run_id=run_id,
            project_revision_id=project_revision_id,
            entity_id=str(simulation_configuration["simulation_configuration_id"]),
            rule_id="SIMULATION_THERMAL_MODEL_NOT_EXECUTABLE",
            severity="blocking_error",
            category="model_resolution",
            message="Requested temperature model is not executable by Phase 3.",
            generated_at=generated_at,
            context={"requested_model_id": thermal_model},
        )

    selected_module = (model_resolution.get("module") or {}).get("selected_model") or {}
    selected_inverter = (
        (model_resolution.get("inverter") or {}).get("selected_model") or {}
    )
    if selected_module.get("model_id") != MODULE_PVSYST_SDM:
        _add(
            findings,
            run_id=run_id,
            project_revision_id=project_revision_id,
            entity_id=topology["module_revision_id"],
            rule_id="SIMULATION_MODULE_MODEL_RESOLVED_BUT_NOT_EXECUTABLE",
            severity="blocking_error",
            category="execution_scope",
            message=(
                "The current numerical kernel executes the detailed PVsyst "
                "single-diode module model only."
            ),
            generated_at=generated_at,
            context={"selected_model_id": selected_module.get("model_id")},
        )
    if selected_inverter.get("model_id") not in {INVERTER_VOLTAGE_DEPENDENT, INVERTER_VOLTAGE_DEPENDENT_BOUNDED}:
        _add(
            findings,
            run_id=run_id,
            project_revision_id=project_revision_id,
            entity_id=topology["inverter_revision_id"],
            rule_id="SIMULATION_INVERTER_MODEL_RESOLVED_BUT_NOT_EXECUTABLE",
            severity="blocking_error",
            category="execution_scope",
            message=(
                "The current numerical kernel executes the voltage-dependent "
                "inverter efficiency model only."
            ),
            generated_at=generated_at,
            context={"selected_model_id": selected_inverter.get("model_id")},
        )

    decomposition = selections.get("irradiance_decomposition")
    if decomposition in {None, "none"}:
        decomposition = None
    elif decomposition not in SUPPORTED_DECOMPOSITION_MODELS:
        _add(
            findings,
            run_id=run_id,
            project_revision_id=project_revision_id,
            entity_id=str(simulation_configuration["simulation_configuration_id"]),
            rule_id="SIMULATION_DECOMPOSITION_MODEL_NOT_EXECUTABLE",
            severity="blocking_error",
            category="model_resolution",
            message="Requested irradiance decomposition model is not executable.",
            generated_at=generated_at,
            context={"requested_model_id": decomposition},
        )

    iam_selection = selections.get("iam")
    if optics_iam is not None:
        iam_model_id = optics_iam[0]
    elif iam_selection in {None, "component_default"}:
        iam_model_id = None
    elif iam_selection in SUPPORTED_IAM_MODELS:
        iam_model_id = iam_selection
        if iam_selection == IAM_TABULATED:
            component_iam = (topology["module"].get("optical") or {}).get("iam") or {}
            if component_iam.get("execution_model_id") != IAM_TABULATED:
                _add(
                    findings,
                    run_id=run_id,
                    project_revision_id=project_revision_id,
                    entity_id=topology["module_revision_id"],
                    rule_id="SIMULATION_EXPLICIT_IAM_PROFILE_UNAVAILABLE",
                    severity="blocking_error",
                    category="model_resolution",
                    message=(
                        "Explicit tabulated IAM was requested but the module "
                        "revision does not provide an executable tabulated profile."
                    ),
                    generated_at=generated_at,
                )
            # Let canonical module semantics construct the profile.
            iam_model_id = None
    else:
        _add(
            findings,
            run_id=run_id,
            project_revision_id=project_revision_id,
            entity_id=str(simulation_configuration["simulation_configuration_id"]),
            rule_id="SIMULATION_IAM_MODEL_NOT_EXECUTABLE",
            severity="blocking_error",
            category="model_resolution",
            message="Requested IAM model is not executable by the current kernel.",
            generated_at=generated_at,
            context={"requested_model_id": iam_selection},
        )
        iam_model_id = None

    output_configuration = simulation_configuration.get("output_configuration") or {}
    if (
        output_configuration.get("format") != "parquet"
        or output_configuration.get("standard_timeseries") is not True
    ):
        _add(
            findings,
            run_id=run_id,
            project_revision_id=project_revision_id,
            entity_id=str(simulation_configuration["simulation_configuration_id"]),
            rule_id="SIMULATION_OUTPUT_CONFIGURATION_UNSUPPORTED",
            severity="blocking_error",
            category="output_configuration",
            message=(
                "Phase 3.8E requires explicit standard_timeseries=true and "
                "format=parquet."
            ),
            generated_at=generated_at,
            context={"output_configuration": output_configuration},
        )

    numerical = simulation_configuration.get("numerical_options") or {}
    thermal = numerical.get("thermal") or {}
    if optics_settings is not None:
        thermal = optics_settings["values"]["thermal"]
    if thermal.get("u_c_w_m2k") is None or thermal.get("u_v_w_m2k_per_ms") is None:
        _add(
            findings,
            run_id=run_id,
            project_revision_id=project_revision_id,
            entity_id=str(simulation_configuration["simulation_configuration_id"]),
            rule_id="SIMULATION_THERMAL_COEFFICIENTS_REQUIRED",
            severity="blocking_error",
            category="numerical_configuration",
            message=(
                "Thermal Uc and Uv must be explicit in "
                "numerical_options.thermal for the current runtime."
            ),
            generated_at=generated_at,
        )

    loss_options = numerical.get("losses") or {}
    resolved_loss_settings = None
    if "loss_settings" in numerical:
        from engine.losses.settings import resolve_loss_settings
        from engine.losses.settings import legacy_loss_settings
        requested_losses = numerical["loss_settings"]
        if not (topology.get("circuit_loss_resolution") or {}).get("active"):
            requested_losses = legacy_loss_settings(requested_losses)
        resolved_loss_settings = resolve_loss_settings(requested_losses)
    for key in (
        "module_mismatch_loss_fraction",
        "string_mismatch_loss_fraction",
        "dc_array_resistance_ohm",
    ):
        if key not in loss_options:
            assumptions.append(
                _runtime_assumption(
                    f"{run_id}:assumption:{key}:zero",
                    kind="fallback",
                    scope="losses",
                    statement=f"{key} defaults to zero for this run.",
                    basis="No explicit value was supplied in numerical_options.losses.",
                    severity="info",
                    source_paths=[f"numerical_options.losses.{key}"],
                    affects=[key],
                )
            )

    if "documented_generic_default_0.20" in topology.get("albedo_sources", (topology["albedo_source"],)):
        assumptions.append(
            _runtime_assumption(
                f"{run_id}:assumption:albedo:0.20",
                kind="fallback",
                scope="irradiance",
                statement="Ground albedo defaults to 0.20 for this run.",
                basis=(
                    "No support-surface albedo or explicit numerical option "
                    "was supplied."
                ),
                severity="info",
                source_paths=[
                    "scene.surfaces[].albedo",
                    "numerical_options.albedo",
                ],
                affects=["poa_ground_diffuse"],
            )
        )

    perez_coefficients = None
    coefficient_data = numerical.get("pvsyst81_perez_coefficient_set")
    if coefficient_data is not None:
        try:
            perez_coefficients = PerezCoefficientSet(
                coefficient_set_id=str(coefficient_data["coefficient_set_id"]),
                timestep_seconds=int(coefficient_data["timestep_seconds"]),
                coefficients=tuple(
                    tuple(float(value) for value in row)
                    for row in coefficient_data["coefficients"]
                ),
                source_reference=str(coefficient_data["source_reference"]),
                pvsyst81_production_verified=bool(
                    coefficient_data.get("pvsyst81_production_verified", False)
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            _add(
                findings,
                run_id=run_id,
                project_revision_id=project_revision_id,
                entity_id=str(simulation_configuration["simulation_configuration_id"]),
                rule_id="SIMULATION_PEREZ_COEFFICIENT_SET_INVALID",
                severity="blocking_error",
                category="numerical_configuration",
                message=f"Explicit Perez coefficient set is invalid: {exc}",
                generated_at=generated_at,
            )

    timestep = int(simulation_configuration["simulation_timestep_seconds"])
    if (
        poa_model == POA_PVSYST81_PEREZ
        and timestep < 3600
        and (
            perez_coefficients is None
            or not perez_coefficients.pvsyst81_production_verified
        )
    ):
        _add(
            findings,
            run_id=run_id,
            project_revision_id=project_revision_id,
            entity_id=str(simulation_configuration["simulation_configuration_id"]),
            rule_id="SIMULATION_PVSYST81_SUBHOURLY_PEREZ_PARITY_BLOCKED",
            severity="blocking_error",
            category="external_model_data",
            message=(
                "Sub-hourly PVsyst 8.1 Perez execution requires a timestep-"
                "matched coefficient set verified as the production table."
            ),
            generated_at=generated_at,
        )

    if _has_blocker(findings):
        return None

    coupling = numerical.get("coupling") or {}
    module_overrides = numerical.get("module_overrides") or {}

    return UnshadedFixedTiltConfiguration(
        simulation_timestep_seconds=timestep,
        surface_tilt_deg=float(topology["surface_tilt_deg"]),
        surface_azimuth_deg=float(topology["surface_azimuth_deg"]),
        poa_model_id=str(poa_model),
        module_definition=topology["module"],
        inverter_definition=topology["inverter"],
        inverter_model_id=selected_inverter["model_id"],
        modules_in_series=int(topology["modules_in_series"]),
        string_ids=tuple(topology["string_ids"]),
        mppt_assignments=topology["mppt_assignments"],
        u_c_w_m2k=float(thermal["u_c_w_m2k"]),
        u_v_w_m2k_per_ms=float(thermal["u_v_w_m2k_per_ms"]),
        alpha_absorption=(
            float(module_overrides["alpha_absorption"])
            if module_overrides.get("alpha_absorption") is not None
            else None
        ),
        thermal_model_id=str(thermal_model),
        albedo=float(topology["albedo"]),
        decomposition_model_id=decomposition,
        perez_model=str(numerical.get("perez_model", "allsitescomposite1990")),
        pvsyst81_perez_coefficient_set=perez_coefficients,
        allow_unverified_pvsyst81_perez_coefficients=False,
        iam_model_id=iam_model_id,
        iam_profile=optics_iam[1] if optics_iam is not None else None,
        optics_thermal_settings=optics_settings,
        module_quality_loss_fraction=(
            float(module_overrides["module_quality_loss_fraction"])
            if module_overrides.get("module_quality_loss_fraction") is not None
            else None
        ),
        loss_settings=resolved_loss_settings,
        circuit_loss_resolution=topology.get("circuit_loss_resolution"),
        inverter_instance_id=topology.get("inverter_instance_id"),
        module_mismatch_loss_fraction=float(
            loss_options.get("module_mismatch_loss_fraction", 0.0)
        ),
        string_mismatch_loss_fraction=float(
            loss_options.get("string_mismatch_loss_fraction", 0.0)
        ),
        dc_array_resistance_ohm=float(
            loss_options.get("dc_array_resistance_ohm", 0.0)
        ),
        solar_delta_t_seconds=(
            float(numerical["solar_delta_t_seconds"])
            if numerical.get("solar_delta_t_seconds") is not None
            else None
        ),
        initial_module_efficiency_fraction=float(
            coupling.get("initial_module_efficiency_fraction", 0.0)
        ),
        temperature_tolerance_c=float(
            coupling.get("temperature_tolerance_c", 1e-4)
        ),
        efficiency_tolerance_fraction=float(
            coupling.get("efficiency_tolerance_fraction", 1e-8)
        ),
        max_coupling_iterations=int(
            coupling.get("max_iterations", 25)
        ),
        coupling_relaxation_factor=float(
            coupling.get("relaxation_factor", 1.0)
        ),
        module_solver=str(numerical.get("module_solver", "lambertw")),
    )


def _weather_findings(
    report: dict[str, Any],
    *,
    run_id: str,
    project_revision_id: str,
    weather_revision_id: str,
    generated_at: str,
    existing_count: int,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for offset, item in enumerate(report["findings"], start=1):
        context = dict(item.get("context") or {})
        context.update(
            {
                "weather_qc_rule_id": item["rule_id"],
                "weather_qc_examples": item.get("examples") or [],
                "weather_qc_count": item.get("count"),
                "weather_qc_variable": item.get("variable"),
            }
        )
        findings.append(
            _finding(
                run_id=run_id,
                ordinal=existing_count + offset,
                project_revision_id=project_revision_id,
                entity_id=weather_revision_id,
                rule_id=item["rule_id"],
                severity=item["severity"],
                category=item["category"],
                message=item["message"],
                generated_at=generated_at,
                context=context,
            )
        )
    if report["status"] == "failed":
        findings.append(
            _finding(
                run_id=run_id,
                ordinal=existing_count + len(findings) + 1,
                project_revision_id=project_revision_id,
                entity_id=weather_revision_id,
                rule_id="SIMULATION_WEATHER_QC_FAILED",
                severity="blocking_error",
                category="simulation_validation_gate",
                message=(
                    "Weather QC contains error/blocking-error findings; the "
                    "simulation validation gate blocks numerical execution."
                ),
                generated_at=generated_at,
                context={
                    "weather_qc_status": report["status"],
                    "finding_counts": report["finding_counts"],
                },
            )
        )
    return findings


def _input_hashes(
    *,
    engine_version: str,
    project_revision: dict[str, Any],
    simulation_configuration: dict[str, Any],
    scene: dict[str, Any],
    electrical: dict[str, Any],
    weather: CanonicalWeather,
    component_manifest: dict[str, Any],
    module: dict[str, Any],
    inverter: dict[str, Any],
) -> dict[str, str]:
    hashes = {
        "engine_version_sha256": canonical_object_sha256(
            {"engine_version": engine_version}
        ),
        "project_revision_sha256": canonical_object_sha256(project_revision),
        "simulation_configuration_sha256": canonical_object_sha256(
            simulation_configuration
        ),
        "scene_revision_sha256": canonical_object_sha256(scene),
        "electrical_revision_sha256": canonical_object_sha256(electrical),
        "weather_dataset_sha256": canonical_object_sha256(weather.dataset),
        "weather_series_logical_sha256": weather_series_logical_sha256(
            weather.series
        ),
        "module_revision_sha256": canonical_object_sha256(module),
        "inverter_revision_sha256": canonical_object_sha256(inverter),
        "component_manifest_sha256": canonical_object_sha256(component_manifest),
    }
    hashes["combined_input_sha256"] = canonical_object_sha256(hashes)
    return hashes


def _failed_run(
    *,
    simulation_run_id: str,
    project_revision: dict[str, Any],
    simulation_configuration: dict[str, Any],
    engine_version: str,
    timestamp: str,
    findings: list[dict[str, Any]],
    assumptions: list[dict[str, Any]],
    model_resolution: dict[str, Any] | None,
    component_manifest: dict[str, Any],
    input_hash: str,
    design_validation_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    run = {
        "schema_name": "SimulationRun",
        "schema_version": "0.1",
        "simulation_run_id": simulation_run_id,
        "project_revision_id": str(
            project_revision.get("project_revision_id")
            or "unresolved-project-revision"
        ),
        "simulation_configuration_id": str(
            simulation_configuration.get("simulation_configuration_id")
            or "unresolved-simulation-configuration"
        ),
        "engine_version": engine_version,
        "started_at": timestamp,
        "completed_at": timestamp,
        "status": "failed",
        "deterministic_seed": None,
        "component_revision_manifest": component_manifest,
        "weather_revision_id": str(
            simulation_configuration.get("weather_dataset_revision_id")
            or project_revision.get("weather_dataset_revision_id")
            or "unresolved-weather"
        ),
        "scene_revision_id": str(
            project_revision.get("scene_revision_id") or "unresolved-scene"
        ),
        "electrical_revision_id": str(
            project_revision.get("electrical_revision_id")
            or "unresolved-electrical"
        ),
        "model_manifest": dict(
            simulation_configuration.get("model_selections") or {}
        ),
        "input_hash": input_hash,
        "result_reference": None,
        "summary_result": None,
        "validation_findings": findings,
        "assumptions": assumptions,
        "model_resolution": model_resolution,
        "reproducibility_manifest": None,
        "job_stage_history": ["queued", "validating", "failed"],
        "log_reference": None,
        "execution_telemetry": {},
        "warning_summary": _warning_summary(
            findings,
            assumptions,
            model_resolution,
        ),
    }
    if design_validation_evidence is not None:
        run.update(
            {
                "design_validation_report_id": (
                    design_validation_evidence.get(
                        "design_validation_report_id"
                    )
                ),
                "design_validation_report_sha256": (
                    design_validation_evidence.get(
                        "design_validation_report_sha256"
                    )
                ),
                "design_validation_rule_set_id": (
                    design_validation_evidence.get(
                        "design_validation_rule_set_id"
                    )
                ),
            }
        )
    from .shading_accuracy import run_shading_accuracy_snapshot
    shading_snapshot = run_shading_accuracy_snapshot(simulation_configuration)
    if shading_snapshot is not None:
        run["resolved_shading_accuracy"] = shading_snapshot
        run["model_manifest"]["resolved_shading_accuracy"] = shading_snapshot
    if (simulation_configuration.get("model_selections") or {}).get("inverter") == INVERTER_VOLTAGE_DEPENDENT_BOUNDED:
        run["model_manifest"]["inverter_voltage_interpolation"] = ADJACENT_ENVELOPE_POLICY
    return run


def run_canonical_simulation(
    project_revision: dict[str, Any],
    simulation_configuration: dict[str, Any],
    *,
    revision_store: CanonicalRevisionStore,
    output_directory: str | Path,
    simulation_run_id: str,
    engine_version: str,
    executed_at: datetime | str | None = None,
    preflight_findings: Sequence[Mapping[str, Any]] = (),
    design_validation_evidence: Mapping[str, Any] | None = None,
    _detailed_context: Mapping[str, Any] | None = None,
) -> CanonicalSimulationExecutionResult:
    """Execute the current numerical kernel through the canonical product contract.

    Legacy fixed-tilt execution preserves its numerical path. Separable standard
    groups execute with one conversion per physical inverter. Unsupported coupled
    topology is reported rather than flattened into an approximate electrical state.
    """
    if not simulation_run_id:
        raise ValueError("simulation_run_id must not be empty")
    if not engine_version:
        raise ValueError("engine_version must not be empty")

    output_path = Path(output_directory)
    run_directory = output_path / simulation_run_id
    existing_run_items = (
        sorted(run_directory.iterdir(), key=lambda item: item.name)
        if run_directory.exists()
        else []
    )
    if existing_run_items:
        staged_validation_path = run_directory / "design-validation-report.json"
        staged_validation_allowed = (
            design_validation_evidence is not None
            and existing_run_items == [staged_validation_path]
            and staged_validation_path.is_file()
        )
        if not staged_validation_allowed:
            raise FileExistsError(
                "simulation_run_id already has persisted artifacts; completed/failed "
                "run packages are immutable"
            )
        try:
            staged_validation = json.loads(
                staged_validation_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(
                "pre-staged design validation report is unreadable"
            ) from exc
        expected_validation_hash = str(
            design_validation_evidence.get(
                "design_validation_report_sha256"
            )
            or ""
        )
        if (
            not expected_validation_hash
            or canonical_object_sha256(staged_validation)
            != expected_validation_hash
        ):
            raise ValueError(
                "pre-staged design validation report does not match "
                "design_validation_evidence"
            )
    now = _timestamp(executed_at)
    project_revision_id = str(
        project_revision.get("project_revision_id") or "unresolved-project-revision"
    )
    findings: list[dict[str, Any]] = [
        deepcopy(dict(item)) for item in preflight_findings
    ]
    assumptions: list[dict[str, Any]] = []

    findings.extend(
        _schema_findings(
            project_revision,
            filename="project-revision.schema.json",
            entity_id=project_revision_id,
            project_revision_id=project_revision_id,
            generated_at=now,
            finding_prefix=f"{simulation_run_id}:schema:project",
        )
    )
    findings.extend(
        _schema_findings(
            simulation_configuration,
            filename="simulation-configuration.schema.json",
            entity_id=str(
                simulation_configuration.get("simulation_configuration_id")
                or "simulation-configuration"
            ),
            project_revision_id=project_revision_id,
            generated_at=now,
            finding_prefix=f"{simulation_run_id}:schema:configuration",
        )
    )

    pre_input_hash = canonical_object_sha256(
        {
            "project_revision": project_revision,
            "simulation_configuration": simulation_configuration,
        }
    )
    shading_request = simulation_configuration.get("shading_configuration")
    detailed_inverter_refusal = None
    if isinstance(shading_request, Mapping) and shading_request.get("electrical_shading_configuration") is not None:
        from .execution_groups import detailed_inverter_scope_finding
        detailed_electrical = revision_store.electrical_revisions.get(project_revision.get("electrical_revision_id"), {})
        detailed_scene = revision_store.scene_revisions.get(project_revision.get("scene_revision_id"), {})
        refusal = detailed_inverter_scope_finding(detailed_scene, detailed_electrical)
        detailed_inverter_refusal = refusal
        if refusal is not None:
            _add(findings, run_id=simulation_run_id, project_revision_id=project_revision_id,
                 entity_id=refusal["entity_id"], rule_id=refusal["rule_id"],
                 severity="blocking_error", category="execution_scope",
                 message=refusal["message"], generated_at=now, context=refusal["context"])
    if (_detailed_context is None and isinstance(shading_request, Mapping) and
        shading_request.get("electrical_shading_configuration") is not None and detailed_inverter_refusal is None):
        from .detailed_dispatch import run_detailed_dispatch
        return run_detailed_dispatch(
            project_revision, simulation_configuration, revision_store=revision_store,
            output_directory=output_path, simulation_run_id=simulation_run_id,
            engine_version=engine_version, executed_at=now, findings=findings,
            design_validation_evidence=design_validation_evidence,
        )
    if _has_blocker(findings):
        run = _failed_run(
            simulation_run_id=simulation_run_id,
            project_revision=project_revision,
            simulation_configuration=simulation_configuration,
            engine_version=engine_version,
            timestamp=now,
            findings=findings,
            assumptions=assumptions,
            model_resolution=None,
            component_manifest={},
            input_hash=pre_input_hash,
            design_validation_evidence=design_validation_evidence,
        )
        _assert_output_schema(run, "simulation-run.schema.json")
        directory = persist_run_package(
            detailed_context=_detailed_context,
            output_directory=output_path,
            simulation_run_id=simulation_run_id,
            simulation_run=run,
            summary_result=None,
            reproducibility_manifest=None,
            validation_findings=findings,
            model_resolution=None,
        )
        return CanonicalSimulationExecutionResult(
            simulation_run=run,
            summary_result=None,
            standard_timeseries=None,
            backend_result=None,
            artifact_directory=directory,
        )

    scene, electrical, weather = _revision_inputs(
        project_revision,
        simulation_configuration,
        revision_store,
        run_id=simulation_run_id,
        generated_at=now,
        findings=findings,
    )

    # _schema() reads from schemas/, so subsystem schemas need direct validation.
    def validate_external_schema(
        instance: Any,
        schema_path: Path,
        entity_id: str,
        prefix: str,
    ) -> None:
        import json

        validator = Draft202012Validator(
            json.loads(schema_path.read_text(encoding="utf-8")),
            registry=_output_registry(),
        )
        for error in sorted(
            validator.iter_errors(instance),
            key=lambda item: list(item.absolute_path),
        ):
            path = ".".join(str(value) for value in error.absolute_path) or "$"
            _add(
                findings,
                run_id=simulation_run_id,
                project_revision_id=project_revision_id,
                entity_id=entity_id,
                rule_id="CANONICAL_SCHEMA_INVALID",
                severity="blocking_error",
                category="canonical_schema",
                message=(
                    f"{schema_path.name} validation failed at {path}: "
                    f"{error.message}"
                ),
                generated_at=now,
                context={
                    "schema_file": str(schema_path.relative_to(ROOT)),
                    "instance_path": path,
                    "prefix": prefix,
                },
            )

    if scene is not None:
        validate_external_schema(
            scene,
            ROOT / "geometry/scene/scene.schema.json",
            str(scene.get("revision_id")),
            "scene",
        )
    if electrical is not None:
        validate_external_schema(
            electrical,
            ROOT / "electrical/schema/electrical-design.schema.json",
            str(electrical.get("electrical_revision_id")),
            "electrical",
        )
    if weather is not None:
        validate_external_schema(
            weather.dataset,
            ROOT / "weather/schema/weather-dataset.schema.json",
            str(weather.dataset.get("revision_id")),
            "weather",
        )

    if scene is not None and electrical is not None and weather is not None and _detailed_context is None:
        candidate_plan = build_simulation_execution_plan(scene, electrical,
            numerical_options=simulation_configuration.get("numerical_options"))
        inverter_count = sum(i.get("enabled") is True for i in electrical.get("inverter_instances", []))
        if candidate_plan.get("mixed_orientation") or candidate_plan["group_count"] > 1 or inverter_count > 1:
            from .multi_group import run_multi_group_canonical
            return run_multi_group_canonical(project_revision=project_revision,
                simulation_configuration=simulation_configuration, revision_store=revision_store,
                output_path=output_path, simulation_run_id=simulation_run_id,
                engine_version=engine_version, now=now, scene=scene, electrical=electrical,
                weather=weather, findings=findings, design_validation_evidence=design_validation_evidence)

    topology = None
    model_resolution = None
    component_manifest: dict[str, Any] = {}

    if scene is not None and electrical is not None:
        topology = _resolve_topology(
            scene,
            electrical,
            revision_store,
            simulation_configuration,
            run_id=simulation_run_id,
            project_revision_id=project_revision_id,
            generated_at=now,
            findings=findings,
            detailed=_detailed_context is not None or (isinstance(shading_request, Mapping) and shading_request.get("electrical_shading_configuration") is not None),
        )

    if topology is not None:
        validate_external_schema(
            topology["module"],
            ROOT / "components/schema/module-definition.schema.json",
            topology["module_revision_id"],
            "module",
        )
        validate_external_schema(
            topology["inverter"],
            ROOT / "components/schema/inverter-definition.schema.json",
            topology["inverter_revision_id"],
            "inverter",
        )
        component_manifest = {
            "module_revision_id": topology["module_revision_id"],
            "inverter_revision_id": topology["inverter_revision_id"],
        }

        selections = simulation_configuration["model_selections"]
        model_resolution_identity = canonical_object_sha256(
            {
                "module_revision_id": topology["module_revision_id"],
                "inverter_revision_id": topology["inverter_revision_id"],
                "requested_module_model_id": selections.get("module_electrical"),
                "requested_inverter_model_id": selections.get("inverter"),
            }
        )
        model_resolution = resolve_simulation_models(
            topology["module"],
            topology["inverter"],
            resolution_id=(
                f"model-resolution:{model_resolution_identity[:16]}"
            ),
            requested_module_model_id=selections.get("module_electrical"),
            requested_inverter_model_id=selections.get("inverter"),
        )
        assumptions.extend(model_resolution["assumptions"])
        if model_resolution["status"] == "blocked":
            _add(
                findings,
                run_id=simulation_run_id,
                project_revision_id=project_revision_id,
                entity_id=str(
                    simulation_configuration["simulation_configuration_id"]
                ),
                rule_id="SIMULATION_MODEL_RESOLUTION_BLOCKED",
                severity="blocking_error",
                category="model_resolution",
                message=(
                    "Component model resolution is blocked; explicit requested "
                    "models cannot be executed from the pinned component revisions."
                ),
                generated_at=now,
                context={"warnings": model_resolution["warnings"]},
            )

    runtime_config = None
    if topology is not None and model_resolution is not None:
        runtime_config = _build_runtime_config(
            simulation_configuration,
            topology,
            model_resolution,
            run_id=simulation_run_id,
            project_revision_id=project_revision_id,
            generated_at=now,
            findings=findings,
            assumptions=assumptions,
        )

    selected_weather = None
    input_hashes = None
    if weather is not None and topology is not None and scene is not None and electrical is not None:
        try:
            selected_weather = _select_weather_period(
                weather,
                simulation_configuration,
            )
        except ValueError as exc:
            _add(
                findings,
                run_id=simulation_run_id,
                project_revision_id=project_revision_id,
                entity_id=str(weather.dataset.get("revision_id")),
                rule_id="SIMULATION_TIME_RANGE_INVALID",
                severity="blocking_error",
                category="time",
                message=str(exc),
                generated_at=now,
            )

        if selected_weather is not None:
            input_hashes = _input_hashes(
                engine_version=engine_version,
                project_revision=project_revision,
                simulation_configuration=simulation_configuration,
                scene=scene,
                electrical=electrical,
                weather=selected_weather,
                component_manifest=component_manifest,
                module=topology["module"],
                inverter=topology["inverter"],
            )

    if _has_blocker(findings) or runtime_config is None or selected_weather is None:
        run = _failed_run(
            simulation_run_id=simulation_run_id,
            project_revision=project_revision,
            simulation_configuration=simulation_configuration,
            engine_version=engine_version,
            timestamp=now,
            findings=findings,
            assumptions=assumptions,
            model_resolution=model_resolution,
            component_manifest=component_manifest,
            input_hash=(
                input_hashes["combined_input_sha256"]
                if input_hashes is not None
                else pre_input_hash
            ),
            design_validation_evidence=design_validation_evidence,
        )
        _assert_output_schema(run, "simulation-run.schema.json")
        directory = persist_run_package(
            detailed_context=_detailed_context,
            output_directory=output_path,
            simulation_run_id=simulation_run_id,
            simulation_run=run,
            summary_result=None,
            reproducibility_manifest=None,
            validation_findings=findings,
            model_resolution=model_resolution,
        )
        return CanonicalSimulationExecutionResult(
            simulation_run=run,
            summary_result=None,
            standard_timeseries=None,
            backend_result=None,
            artifact_directory=directory,
        )

    # Canonical validation uses the same temporal transformation and solar position
    # semantics as numerical execution. The backend may recompute these deterministic
    # stages; future caching can remove this duplication without changing the contract.
    temporal_for_qc = prepare_temporal_execution(
        selected_weather,
        simulation_timestep_seconds=runtime_config.simulation_timestep_seconds,
    )
    solar_for_qc = solar_position_from_weather(
        temporal_for_qc.weather,
        timeline=temporal_for_qc.timeline,
        delta_t_seconds=runtime_config.solar_delta_t_seconds,
    )
    weather_qc = run_solar_aware_weather_qc(
        temporal_for_qc.weather,
        solar_for_qc,
    )
    findings.extend(
        _weather_findings(
            weather_qc,
            run_id=simulation_run_id,
            project_revision_id=project_revision_id,
            weather_revision_id=str(selected_weather.dataset["revision_id"]),
            generated_at=now,
            existing_count=len(findings),
        )
    )

    if _has_blocker(findings):
        run = _failed_run(
            simulation_run_id=simulation_run_id,
            project_revision=project_revision,
            simulation_configuration=simulation_configuration,
            engine_version=engine_version,
            timestamp=now,
            findings=findings,
            assumptions=assumptions,
            model_resolution=model_resolution,
            component_manifest=component_manifest,
            input_hash=input_hashes["combined_input_sha256"],
            design_validation_evidence=design_validation_evidence,
        )
        _assert_output_schema(run, "simulation-run.schema.json")
        directory = persist_run_package(
            detailed_context=_detailed_context,
            output_directory=output_path,
            simulation_run_id=simulation_run_id,
            simulation_run=run,
            summary_result=None,
            reproducibility_manifest=None,
            validation_findings=findings,
            model_resolution=model_resolution,
        )
        return CanonicalSimulationExecutionResult(
            simulation_run=run,
            summary_result=None,
            standard_timeseries=None,
            backend_result=None,
            artifact_directory=directory,
        )

    shading_execution_mode = topology["shading_execution_mode"]
    geometry_modes = {
        "beam_only_geometry",
        "beam_sky_geometry",
        "beam_sky_ground_geometry",
    }

    receiver_factor_sink: ReceiverFactorParquetSink | None = None
    geometry_receiver_factor_kwargs: dict[str, Any] = {}
    predicted_receiver_factor_rows = 0
    if shading_execution_mode in geometry_modes:
        groups = topology["execution_group_plan"].get("groups") or []
        receiver_count = (
            len(groups[0].get("receiver_ids") or [])
            if len(groups) == 1
            else 0
        )
        predicted_receiver_factor_rows = (
            len(temporal_for_qc.weather.series) * receiver_count
        )
        if (
            receiver_count > 0
            and predicted_receiver_factor_rows
            > RECEIVER_FACTOR_STREAMING_ROW_THRESHOLD
        ):
            receiver_factor_sink = ReceiverFactorParquetSink(
                output_directory=output_path,
                simulation_run_id=simulation_run_id,
            )
            geometry_receiver_factor_kwargs = {
                "receiver_factor_chunk_consumer": receiver_factor_sink.write,
                "retain_receiver_factors": False,
                "receiver_factor_chunk_rows": (
                    RECEIVER_FACTOR_STREAMING_CHUNK_ROWS
                ),
            }
    if shading_execution_mode in geometry_modes:
        assumptions.append(
            _runtime_assumption(
                "phase55_beam_visibility_area_weighted_electrical_approximation",
                kind="limitation",
                scope="execution_group",
                statement=(
                    "Module-level geometric beam visibility is area-weighted "
                    "to one homogeneous execution-group beam modifier before "
                    "the existing electrical model; electrical mismatch is not modeled."
                ),
                basis=BEAM_VISIBILITY_AGGREGATION_METHOD_ID,
                severity="warning",
                source_paths=(
                    "Scene.module_instances",
                    "CompiledShadingGeometry.receivers",
                    "SimulationExecutionGroupPlan.groups",
                ),
                affects=(
                    "poa_beam_w_m2",
                    "effective_irradiance_w_m2",
                    "module_pmp_w",
                    "pcc_power_w",
                ),
            )
        )

        if shading_execution_mode in {
            "beam_sky_geometry",
            "beam_sky_ground_geometry",
        }:
            assumptions.append(
                _runtime_assumption(
                    "phase56_component_diffuse_geometry_approximation",
                    kind="limitation",
                    scope="execution_group",
                    statement=(
                        "Receiver isotropic-sky and horizon visibility are "
                        "calculated on explicitly discretized weighted sky domes "
                        "and area-weighted to homogeneous execution-group factors. "
                        "Circumsolar visibility reuses the current sun-direction "
                        "beam visibility. Signed empirical horizon components are "
                        "scaled linearly; electrical mismatch is not modeled."
                    ),
                    basis=DIFFUSE_VISIBILITY_AGGREGATION_METHOD_ID,
                    severity="warning",
                    source_paths=(
                        "Scene.module_instances",
                        "CompiledShadingGeometry.receivers",
                        "SimulationConfiguration.shading_configuration.sky_dome_resolution",
                    ),
                    affects=(
                        "poa_isotropic_w_m2",
                        "poa_circumsolar_w_m2",
                        "poa_horizon_w_m2",
                        "poa_sky_diffuse_w_m2",
                        "effective_irradiance_w_m2",
                        "pcc_power_w",
                    ),
                )
            )

        try:
            if shading_execution_mode == "beam_sky_ground_geometry":
                assumptions.append(
                    _runtime_assumption(
                        "phase57_uniform_ground_view_geometry_approximation",
                        kind="limitation",
                        scope="execution_group",
                        statement=(
                            "Receiver-side lower-hemisphere ground visibility is "
                            "calculated against the existing uniform Lambertian "
                            "scalar-albedo ground-reflected POA component and "
                            "area-weighted to one homogeneous execution-group factor. "
                            "Spatial shadowing of ground irradiance, bifacial rear "
                            "irradiance, and electrical mismatch are not modeled."
                        ),
                        basis=GROUND_VISIBILITY_AGGREGATION_METHOD_ID,
                        severity="warning",
                        source_paths=(
                            "Scene.module_instances",
                            "CompiledShadingGeometry.receivers",
                            "SimulationConfiguration.shading_configuration.ground_dome_resolution",
                        ),
                        affects=(
                            "poa_ground_diffuse_w_m2",
                            "poa_global_w_m2",
                            "effective_irradiance_w_m2",
                            "pcc_power_w",
                        ),
                    )
                )
                backend = run_beam_sky_ground_shaded_fixed_tilt(
                    selected_weather,
                    config=runtime_config,
                    compiled_geometry=topology["compiled_shading_geometry"],
                    execution_group_plan=topology["execution_group_plan"],
                    shading_configuration=simulation_configuration[
                        "shading_configuration"
                    ],
                    **geometry_receiver_factor_kwargs,
                )
            elif shading_execution_mode == "beam_sky_geometry":
                backend = run_beam_sky_shaded_fixed_tilt(
                    selected_weather,
                    config=runtime_config,
                    compiled_geometry=topology["compiled_shading_geometry"],
                    execution_group_plan=topology["execution_group_plan"],
                    shading_configuration=simulation_configuration[
                        "shading_configuration"
                    ],
                    **geometry_receiver_factor_kwargs,
                )
            else:
                backend = run_beam_shaded_fixed_tilt(
                    selected_weather,
                    config=runtime_config,
                    compiled_geometry=topology["compiled_shading_geometry"],
                    execution_group_plan=topology["execution_group_plan"],
                    shading_configuration=simulation_configuration[
                        "shading_configuration"
                    ],
                    **geometry_receiver_factor_kwargs,
                )
        except Exception:
            if receiver_factor_sink is not None:
                receiver_factor_sink.abort()
            raise
    else:
        backend = run_unshaded_fixed_tilt(
            selected_weather,
            config=runtime_config,
        )

    if shading_execution_mode in geometry_modes:
        backend.metadata.setdefault("execution_telemetry", {})
        backend.metadata["execution_telemetry"]["receiver_factor_persistence"] = {
            "predicted_row_count": predicted_receiver_factor_rows,
            "streaming_threshold_rows": RECEIVER_FACTOR_STREAMING_ROW_THRESHOLD,
            "streaming_enabled": receiver_factor_sink is not None,
            "chunk_rows": (
                RECEIVER_FACTOR_STREAMING_CHUNK_ROWS
                if receiver_factor_sink is not None
                else None
            ),
        }

        executed_duration_h = float(
            backend.timeseries["duration_seconds"].sum()
        ) / 3600.0
        if (
            isclose(executed_duration_h, 8760.0, abs_tol=1e-9)
            or isclose(executed_duration_h, 8784.0, abs_tol=1e-9)
        ):
            try:
                counterfactual_backend = run_unshaded_fixed_tilt(
                    selected_weather,
                    config=runtime_config,
                )
            except Exception:
                if receiver_factor_sink is not None:
                    receiver_factor_sink.abort()
                raise
            actual_energy_wh = (
                float(backend.energy.annual["pcc_power_kwh"]) * 1000.0
            )
            counterfactual_energy_wh = (
                float(counterfactual_backend.energy.annual["pcc_power_kwh"])
                * 1000.0
            )
            backend.metadata["shading_energy_counterfactual"] = {
                "method_id": (
                    "phase59.same_run_inputs_geometric_visibility_forced_clear.v0.1"
                ),
                "scope": "geometric_near_shading_only",
                "actual_pcc_energy_wh": actual_energy_wh,
                "counterfactual_pcc_energy_wh": counterfactual_energy_wh,
                "shading_energy_loss_wh": (
                    counterfactual_energy_wh - actual_energy_wh
                ),
                "sign_convention": (
                    "positive means geometric near shading reduced PCC energy"
                ),
                "same_weather": True,
                "same_design": True,
                "same_optical_iam_models": True,
                "same_thermal_model": True,
                "same_electrical_model": True,
                "same_non_shading_losses": True,
                "counterfactual_visibility": (
                    "beam_sky_ground_geometric_visibility_forced_to_one"
                ),
                "electrical_mismatch_included": False,
            }

    resolved_numerical_options = {
        "thermal": {
            "u_c_w_m2k": runtime_config.u_c_w_m2k,
            "u_v_w_m2k_per_ms": runtime_config.u_v_w_m2k_per_ms,
        },
        "albedo": runtime_config.albedo,
        "perez_model": runtime_config.perez_model,
        "losses": {
            "module_quality_loss_fraction_override": (
                runtime_config.module_quality_loss_fraction
            ),
            "module_mismatch_loss_fraction": (
                runtime_config.module_mismatch_loss_fraction
            ),
            "string_mismatch_loss_fraction": (
                runtime_config.string_mismatch_loss_fraction
            ),
            "dc_array_resistance_ohm": runtime_config.dc_array_resistance_ohm,
        },
        "coupling": {
            "initial_module_efficiency_fraction": (
                runtime_config.initial_module_efficiency_fraction
            ),
            "temperature_tolerance_c": runtime_config.temperature_tolerance_c,
            "efficiency_tolerance_fraction": (
                runtime_config.efficiency_tolerance_fraction
            ),
            "max_iterations": runtime_config.max_coupling_iterations,
            "relaxation_factor": runtime_config.coupling_relaxation_factor,
        },
        "module_solver": runtime_config.module_solver,
        "solar_delta_t_seconds": runtime_config.solar_delta_t_seconds,
        "albedo_source": topology["albedo_source"],
    }

    standard_timeseries = build_standard_timeseries(backend)
    result_reference = persist_parquet_result(
        standard_timeseries,
        output_directory=output_path,
        simulation_run_id=simulation_run_id,
    )

    shading_receiver_factor_reference = None
    if receiver_factor_sink is not None:
        shading_receiver_factor_reference = receiver_factor_sink.finalize()
        backend.metadata["execution_telemetry"][
            "receiver_factor_persistence"
        ].update(receiver_factor_sink.telemetry())
    elif backend.shading_receiver_factors is not None:
        shading_receiver_factor_reference = persist_receiver_factor_result(
            backend.shading_receiver_factors,
            output_directory=output_path,
            simulation_run_id=simulation_run_id,
        )
        backend.metadata.setdefault("execution_telemetry", {})
        backend.metadata["execution_telemetry"]["receiver_factor_persistence"] = {
            "predicted_row_count": len(backend.shading_receiver_factors),
            "streaming_threshold_rows": RECEIVER_FACTOR_STREAMING_ROW_THRESHOLD,
            "streaming_enabled": False,
            "mode": "in_memory_then_parquet",
            "row_count": len(backend.shading_receiver_factors),
        }
    if shading_receiver_factor_reference is not None:
        _assert_output_schema(
            shading_receiver_factor_reference,
            "result-dataset-reference.schema.json",
        )

    annual_shading_result = None
    if shading_execution_mode in geometry_modes:
        if shading_receiver_factor_reference is None:
            raise RuntimeError(
                "geometry-aware execution completed without a receiver-factor dataset"
            )
        annual_shading_result = build_annual_shading_result(
            compiled_geometry=topology["compiled_shading_geometry"],
            execution_group_plan=topology["execution_group_plan"],
            shading_configuration=simulation_configuration[
                "shading_configuration"
            ],
            shading_runtime=backend.metadata["shading_runtime"],
            dataset_reference=shading_receiver_factor_reference,
        )
        _assert_output_schema(
            annual_shading_result,
            "geometry/shading/shading-result.schema.json",
        )
        if (
            annual_shading_result["dataset_reference"]
            != shading_receiver_factor_reference
        ):
            raise RuntimeError(
                "annual ShadingResult dataset reference diverged from the "
                "SimulationRun compatibility receiver-factor reference"
            )

    data_quality_summary = {
        "status": weather_qc["status"],
        "finding_counts": weather_qc["finding_counts"],
        "solar_aware": True,
    }
    summary = build_summary_result(
        backend,
        simulation_run_id=simulation_run_id,
        data_quality_summary=data_quality_summary,
    )
    _assert_output_schema(summary, "summary-result.schema.json")
    _assert_output_schema(result_reference, "result-dataset-reference.schema.json")

    if simulation_configuration.get("numerical_options", {}).get("optics_thermal_settings") is not None:
        from .optics_thermal import run_optics_snapshot
        backend.metadata["resolved_optics_thermal_settings"] = run_optics_snapshot(
            simulation_configuration, revision_store.scene_revisions[project_revision["scene_revision_id"]],
            revision_store.electrical_revisions[project_revision["electrical_revision_id"]], revision_store.component_revisions)
    return _persist_completed_execution(
        project_revision=project_revision, simulation_configuration=simulation_configuration,
        project_revision_id=project_revision_id, simulation_run_id=simulation_run_id,
        engine_version=engine_version, now=now, backend=backend, topology=topology,
        model_resolution=model_resolution, component_manifest=component_manifest,
        selected_weather=selected_weather, weather_qc=weather_qc, findings=findings,
        assumptions=assumptions, input_hashes=input_hashes, result_reference=result_reference,
        shading_receiver_factor_reference=shading_receiver_factor_reference,
        annual_shading_result=annual_shading_result,
        resolved_numerical_options=resolved_numerical_options, summary=summary,
        standard_timeseries=standard_timeseries, output_path=output_path,
        design_validation_evidence=design_validation_evidence, _detailed_context=_detailed_context,
    )


def _persist_completed_execution(*, project_revision, simulation_configuration, project_revision_id, simulation_run_id,
    engine_version, now, backend, topology, model_resolution, component_manifest,
    selected_weather, weather_qc, findings, assumptions, input_hashes,
    result_reference, shading_receiver_factor_reference, annual_shading_result,
    resolved_numerical_options, summary, standard_timeseries, output_path,
    design_validation_evidence, _detailed_context=None):
    model_manifest = {
        **backend.metadata["model_manifest"],
        "requested_model_selections": dict(
            simulation_configuration.get("model_selections") or {}
        ),
        "component_model_resolution_id": (
            model_resolution["resolution_id"] if model_resolution is not None
            else backend.metadata["execution_model_resolution_id"]
        ),
        "execution_scope": backend.metadata["scope"],
        "execution_group_plan_id": topology["execution_group_plan"][
            "execution_plan_id"
        ],
        "execution_group_plan_payload_sha256": topology[
            "execution_group_plan"
        ]["execution_plan_payload_sha256"],
        "execution_group_class": topology["execution_group_plan"][
            "execution_class"
        ],
        "execution_group_count": topology["execution_group_plan"][
            "group_count"
        ],
        "near_shading_runtime": backend.metadata.get("shading_runtime"),
        "electrical_shading_scope": (
            "not_modeled"
            if topology["shading_execution_mode"] in {
                "beam_only_geometry",
                "beam_sky_geometry",
                "beam_sky_ground_geometry",
            }
            else "not_applicable_unshaded"
        ),
        "shading_receiver_factor_logical_content_sha256": (
            shading_receiver_factor_reference["logical_content_sha256"]
            if shading_receiver_factor_reference is not None
            else None
        ),
        "weather_qc_policy_id": (
            next(
                (
                    item.get("context", {}).get("policy_id")
                    for item in weather_qc["findings"]
                    if item.get("context", {}).get("policy_id")
                ),
                "weather_qc.solar_aware.bsrn_v2_rawibumi.v0.1",
            )
        ),
    }

    if (simulation_configuration.get("model_selections") or {}).get("inverter") == INVERTER_VOLTAGE_DEPENDENT_BOUNDED:
        if backend.metadata["model_manifest"].get("inverter") != INVERTER_VOLTAGE_DEPENDENT_BOUNDED:
            raise ValueError("resolved inverter model did not reach the numerical kernel")
        model_manifest.update(inverter=INVERTER_VOLTAGE_DEPENDENT_BOUNDED,
                              inverter_voltage_interpolation=ADJACENT_ENVELOPE_POLICY)
    if "resolved_loss_settings" in backend.electrical.ledger.metadata:
        model_manifest["resolved_loss_settings"] = backend.electrical.ledger.metadata["resolved_loss_settings"]

    if "resolved_optics_thermal_settings" in backend.metadata:
        model_manifest["resolved_optics_thermal_settings"] = backend.metadata["resolved_optics_thermal_settings"]
        if hasattr(backend, "groups"):
            model_manifest["optics_input_limits"] = {gid: {k: group.dc.poa.metadata[k] for k in ("zero_input_policy", "zero_input_interval_count") if k in group.dc.poa.metadata}
                for gid, group in backend.groups.items()}
        else:
            model_manifest["optics_input_limits"] = {k: backend.poa.metadata[k] for k in ("zero_input_policy", "zero_input_interval_count") if k in backend.poa.metadata}

    from .shading_accuracy import run_shading_accuracy_snapshot
    shading_snapshot = run_shading_accuracy_snapshot(simulation_configuration)
    if shading_snapshot is not None:
        model_manifest["resolved_shading_accuracy"] = shading_snapshot

    reproducibility = {
        "schema_name": "ReproducibilityManifest",
        "schema_version": "0.1",
        "project_revision_id": project_revision_id,
        "scene_revision_id": str(project_revision["scene_revision_id"]),
        "electrical_revision_id": str(project_revision["electrical_revision_id"]),
        "weather_revision_id": str(selected_weather.dataset["revision_id"]),
        "component_revision_manifest": component_manifest,
        "engine_version": engine_version,
        "model_manifest": model_manifest,
        "simulation_timestep_seconds": int(
            simulation_configuration["simulation_timestep_seconds"]
        ),
        "timezone": str(backend.temporal.weather.series.index.tz),
        "native_weather_resolution_seconds": int(
            backend.temporal.metadata["native_resolution_seconds"]
        ),
        "working_weather_resolution_seconds": int(
            backend.temporal.metadata["simulation_timestep_seconds"]
        ),
        "source_timestamp_convention": str(
            selected_weather.dataset["source_timestamp_convention"]
        ),
        "representative_time_policy": str(
            backend.temporal.timeline.metadata["representative_time_policy"]
        ),
        "solar_evaluation_offset_minutes": float(
            backend.temporal.timeline.metadata["solar_evaluation_offset_minutes"]
        ),
        "weather_transformations": list(
            backend.temporal.weather.dataset.get("transformations") or []
        ),
        "loss_models": list(simulation_configuration.get("loss_model_ids") or []),
        "shading_configuration": dict(
            simulation_configuration.get("shading_configuration") or {}
        ),
        "numerical_options": resolved_numerical_options,
        "output_configuration": dict(
            simulation_configuration.get("output_configuration") or {}
        ),
        "result_logical_content_sha256": result_reference[
            "logical_content_sha256"
        ],
        "result_file_sha256": result_reference["sha256"],
        "shading_receiver_factor_reference": shading_receiver_factor_reference,
        "shading_result_id": (
            annual_shading_result["shading_result_id"]
            if annual_shading_result is not None
            else None
        ),
        "shading_result_payload_sha256": (
            annual_shading_result["result_payload_sha256"]
            if annual_shading_result is not None
            else None
        ),
        "shading_physical_result_sha256": (
            annual_shading_result["physical_result_sha256"]
            if annual_shading_result is not None
            else None
        ),
        "input_hashes": input_hashes,
    }
    if design_validation_evidence is not None:
        reproducibility.update(
            {
                "design_validation_report_id": (
                    design_validation_evidence.get(
                        "design_validation_report_id"
                    )
                ),
                "design_validation_report_sha256": (
                    design_validation_evidence.get(
                        "design_validation_report_sha256"
                    )
                ),
                "design_validation_rule_set_id": (
                    design_validation_evidence.get(
                        "design_validation_rule_set_id"
                    )
                ),
            }
        )
    _assert_output_schema(
        reproducibility,
        "reproducibility-manifest.schema.json",
    )

    warning_status = (
        any(item["severity"] in {"warning", "recommendation"} for item in findings)
        or any(item.get("severity") == "warning" for item in assumptions)
        or bool((model_resolution or {}).get("warnings"))
        or any(item["resolution"].get("warnings") for item in
               backend.metadata.get("execution_model_resolutions", []))
    )
    status = "completed_with_warnings" if warning_status else "completed"

    run = {
        "schema_name": "SimulationRun",
        "schema_version": "0.1",
        "simulation_run_id": simulation_run_id,
        "project_revision_id": project_revision_id,
        "simulation_configuration_id": str(
            simulation_configuration["simulation_configuration_id"]
        ),
        "engine_version": engine_version,
        "started_at": now,
        "completed_at": now,
        "status": status,
        "deterministic_seed": None,
        "component_revision_manifest": component_manifest,
        "weather_revision_id": str(selected_weather.dataset["revision_id"]),
        "scene_revision_id": str(project_revision["scene_revision_id"]),
        "electrical_revision_id": str(project_revision["electrical_revision_id"]),
        "model_manifest": model_manifest,
        "input_hash": input_hashes["combined_input_sha256"],
        "result_reference": result_reference,
        "shading_receiver_factor_reference": shading_receiver_factor_reference,
        "shading_result": annual_shading_result,
        "summary_result": summary,
        "validation_findings": findings,
        "assumptions": assumptions,
        "model_resolution": model_resolution,
        "reproducibility_manifest": reproducibility,
        "job_stage_history": [
            "queued",
            "validating",
            "preprocessing",
            "simulating",
            "aggregating",
            "reconciling",
            "completed",
        ],
        "log_reference": None,
        "execution_telemetry": dict(
            backend.metadata.get("execution_telemetry") or {}
        ),
        "warning_summary": _warning_summary(
            findings,
            assumptions,
            model_resolution,
        ),
    }
    if shading_snapshot is not None:
        run["resolved_shading_accuracy"] = shading_snapshot
    if backend.metadata.get("mixed_orientation") is not None:
        run["mixed_orientation"] = backend.metadata["mixed_orientation"]
    if topology.get("circuit_loss_resolution") is not None:
        from engine.losses.settings import completed_circuit_loss_audit
        run["circuit_loss_resolution"] = completed_circuit_loss_audit(topology["circuit_loss_resolution"], backend)
    if "resolved_optics_thermal_settings" in backend.metadata:
        run["resolved_optics_thermal_settings"] = backend.metadata["resolved_optics_thermal_settings"]
    if "execution_model_resolutions" in backend.metadata:
        run["execution_model_resolutions"] = backend.metadata["execution_model_resolutions"]
        run["warning_summary"]["warning_count"] += sum(
            len(item["resolution"].get("warnings") or [])
            for item in run["execution_model_resolutions"]
        )
    if design_validation_evidence is not None:
        run.update(
            {
                "design_validation_report_id": (
                    design_validation_evidence.get(
                        "design_validation_report_id"
                    )
                ),
                "design_validation_report_sha256": (
                    design_validation_evidence.get(
                        "design_validation_report_sha256"
                    )
                ),
                "design_validation_rule_set_id": (
                    design_validation_evidence.get(
                        "design_validation_rule_set_id"
                    )
                ),
            }
        )
    _assert_output_schema(run, "simulation-run.schema.json")
    directory = persist_run_package(
        detailed_context=_detailed_context,
        output_directory=output_path,
        simulation_run_id=simulation_run_id,
        simulation_run=run,
        summary_result=summary,
        reproducibility_manifest=reproducibility,
        validation_findings=findings,
        model_resolution=model_resolution,
        shading_result=annual_shading_result,
    )

    return CanonicalSimulationExecutionResult(
        simulation_run=run,
        summary_result=summary,
        standard_timeseries=standard_timeseries,
        backend_result=backend,
        artifact_directory=directory,
    )
