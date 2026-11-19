"""Phase-4.8 Design -> Simulation integration boundary.


This module bridges canonical Phase-4 design revisions into the existing canonical
simulation orchestrator without introducing a second design model. UI/workspace
state is deliberately absent from every public execution contract here.
"""


from __future__ import annotations


from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


from jsonschema import Draft202012Validator
from referencing import Registry, Resource


from validation.engineering import ENGINEERING_RULE_SET_ID
from weather.core import CanonicalWeather


from .artifacts import canonical_object_sha256, persist_json_artifact
from .detailed_inputs import FrozenDetailedSelectionSnapshot
from .canonical import (
    CanonicalRevisionStore,
    CanonicalSimulationExecutionResult,
    run_canonical_simulation,
)




ROOT = Path(__file__).resolve().parents[2]




@dataclass(frozen=True)
class DesignSimulationPreparation:
    """Pinned execution objects plus derived validation-gate evidence."""


    project_revision: dict[str, Any]
    simulation_configuration: dict[str, Any]
    revision_store: CanonicalRevisionStore
    design_validation_report: dict[str, Any]
    preflight_findings: tuple[dict[str, Any], ...]
    design_validation_evidence: dict[str, Any]




@dataclass(frozen=True)
class DesignStatePackage:
    """Reloaded canonical Phase-4 design state plus integrity manifest."""


    scene: dict[str, Any]
    electrical_design: dict[str, Any]
    project_revision: dict[str, Any]
    simulation_configuration: dict[str, Any]
    design_validation_report: dict[str, Any]
    manifest: dict[str, Any]




def _timestamp(value: datetime | str | None) -> str:
    if value is None:
        resolved = datetime.now(timezone.utc)
    elif isinstance(value, str):
        resolved = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        resolved = value
    if resolved.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return resolved.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")




def _schema_registry() -> Registry:
    registry = Registry()
    for directory in (
        ROOT / "schemas",
        ROOT / "components/schema",
        ROOT / "weather/schema",
        ROOT / "geometry/scene",
        ROOT / "geometry/coordinates",
        ROOT / "geometry/scene3d",
        ROOT / "geometry/shading",
        ROOT / "electrical/schema",
        ROOT / "shading/electrical",
        ROOT / "apps/web/schema",
    ):
        for path in directory.glob("*.schema.json"):
            schema = json.loads(path.read_text(encoding="utf-8"))
            if "$id" in schema:
                registry = registry.with_resource(
                    schema["$id"], Resource.from_contents(schema)
                )
    return registry




def _validate_schema(value: Mapping[str, Any], filename: str) -> list[str]:
    schema = json.loads((ROOT / "schemas" / filename).read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, registry=_schema_registry())
    errors = sorted(
        validator.iter_errors(value),
        key=lambda item: list(item.absolute_path),
    )
    return [
        (
            ".".join(str(part) for part in error.absolute_path) or "$"
        )
        + ": "
        + error.message
        for error in errors
    ]




def _gate_finding(
    *,
    project_revision_id: str,
    report_id: str,
    rule_id: str,
    message: str,
    generated_at: str,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_name": "ValidationFinding",
        "schema_version": "0.1",
        "finding_id": f"{report_id}:phase48:{rule_id.lower()}",
        "project_revision_id": project_revision_id,
        "entity_id": report_id,
        "rule_id": rule_id,
        "severity": "blocking_error",
        "category": "design_simulation_gate",
        "message": message,
        "measured_value": None,
        "limit_value": None,
        "unit": None,
        "context": deepcopy(dict(context or {})),
        "generated_at": generated_at,
        "resolved_at": None,
        "resolution_note": None,
    }




def build_project_revision_from_design(
    scene: Mapping[str, Any],
    electrical_design: Mapping[str, Any],
    *,
    project_revision_id: str,
    revision_number: int,
    weather_dataset_revision_id: str,
    simulation_defaults_revision_id: str | None = None,
    change_summary: str | None = None,
) -> dict[str, Any]:
    """Pin exact Scene/Electrical/Weather revisions into a ProjectRevision."""
    if not project_revision_id:
        raise ValueError("project_revision_id is required")
    if revision_number < 1:
        raise ValueError("revision_number must be at least 1")
    if not weather_dataset_revision_id:
        raise ValueError("weather_dataset_revision_id is required")


    scene_project = str(scene.get("project_id") or "")
    electrical_project = str(electrical_design.get("project_id") or "")
    if not scene_project or not electrical_project:
        raise ValueError("Scene and ElectricalDesignRevision must identify project_id")
    if scene_project != electrical_project:
        raise ValueError("Scene and ElectricalDesignRevision project_id must match")


    embedded_ids = set()
    root_project_revision_id = electrical_design.get("project_revision_id")
    if root_project_revision_id is not None:
        embedded_ids.add(str(root_project_revision_id))
    for collection in ("inverter_instances", "strings", "connections"):
        for item in electrical_design.get(collection, []):
            value = item.get("project_revision_id")
            if value is not None:
                embedded_ids.add(str(value))
    if embedded_ids and embedded_ids != {project_revision_id}:
        raise ValueError(
            "Electrical design contains project_revision_id values that do not "
            "match the ProjectRevision being created"
        )


    scene_revision_id = str(scene.get("revision_id") or "")
    electrical_revision_id = str(
        electrical_design.get("electrical_revision_id") or ""
    )
    if not scene_revision_id or not electrical_revision_id:
        raise ValueError("committed Scene and ElectricalDesignRevision IDs are required")


    project_revision = {
        "schema_name": "ProjectRevision",
        "schema_version": "0.1",
        "project_revision_id": project_revision_id,
        "revision_number": int(revision_number),
        "scene_revision_id": scene_revision_id,
        "electrical_revision_id": electrical_revision_id,
        "weather_dataset_revision_id": weather_dataset_revision_id,
        "simulation_defaults_revision_id": simulation_defaults_revision_id,
        "change_summary": change_summary,
    }
    errors = _validate_schema(
        project_revision, "project-revision.schema.json"
    )
    if errors:
        raise ValueError("invalid ProjectRevision: " + "; ".join(errors))
    return project_revision




def build_simulation_configuration_from_design(
    project_revision: Mapping[str, Any],
    *,
    simulation_configuration_id: str,
    simulation_timestep_seconds: int,
    model_selections: Mapping[str, str],
    shading_configuration: Mapping[str, Any],
    numerical_options: Mapping[str, Any],
    output_configuration: Mapping[str, Any],
    loss_model_ids: Sequence[str] = (),
    name: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
) -> dict[str, Any]:
    """Create an explicit canonical SimulationConfiguration for one design revision."""
    project_errors = _validate_schema(
        project_revision, "project-revision.schema.json"
    )
    if project_errors:
        raise ValueError(
            "invalid ProjectRevision: " + "; ".join(project_errors)
        )
    weather_revision_id = project_revision.get("weather_dataset_revision_id")
    if not weather_revision_id:
        raise ValueError(
            "ProjectRevision must pin weather_dataset_revision_id before simulation"
        )
    if simulation_timestep_seconds < 1:
        raise ValueError("simulation_timestep_seconds must be positive")
    if not simulation_configuration_id:
        raise ValueError("simulation_configuration_id is required")


    configuration = {
        "schema_name": "SimulationConfiguration",
        "schema_version": "0.1",
        "simulation_configuration_id": simulation_configuration_id,
        "project_revision_id": str(project_revision["project_revision_id"]),
        "name": name,
        "simulation_timestep_seconds": int(simulation_timestep_seconds),
        "start_time": start_time,
        "end_time": end_time,
        "weather_dataset_revision_id": str(weather_revision_id),
        "model_selections": deepcopy(dict(model_selections)),
        "loss_model_ids": [str(value) for value in loss_model_ids],
        "shading_configuration": deepcopy(dict(shading_configuration)),
        "numerical_options": deepcopy(dict(numerical_options)),
        "output_configuration": deepcopy(dict(output_configuration)),
    }
    errors = _validate_schema(
        configuration, "simulation-configuration.schema.json"
    )
    if errors:
        raise ValueError(
            "invalid SimulationConfiguration: " + "; ".join(errors)
        )
    return configuration




def referenced_component_revision_ids(
    scene: Mapping[str, Any],
    electrical_design: Mapping[str, Any],
) -> tuple[str, ...]:
    """Return the exact component revision IDs referenced by the canonical design."""
    revision_ids: set[str] = set()
    for field in scene.get("pv_fields", []):
        revision_id = field.get("module_definition_revision_id")
        if revision_id:
            revision_ids.add(str(revision_id))
    for module in scene.get("module_instances", []):
        revision_id = module.get("module_definition_revision_id")
        if revision_id:
            revision_ids.add(str(revision_id))
    for inverter in electrical_design.get("inverter_instances", []):
        revision_id = inverter.get("inverter_definition_revision_id")
        if revision_id:
            revision_ids.add(str(revision_id))
    return tuple(sorted(revision_ids))




def build_design_revision_store(
    scene: Mapping[str, Any],
    electrical_design: Mapping[str, Any],
    weather: CanonicalWeather,
    component_revisions: Mapping[str, Mapping[str, Any]],
    *,
    detailed_electrical_inputs: FrozenDetailedSelectionSnapshot | None = None,
) -> CanonicalRevisionStore:
    """Build the immutable lookup surface required by the canonical worker."""
    refs = referenced_component_revision_ids(scene, electrical_design)
    normalized_components: dict[str, dict[str, Any]] = {}
    for key, value in component_revisions.items():
        revision_id = str(value.get("revision_id") or "")
        if not revision_id:
            raise ValueError(f"component mapping {key!r} has no revision_id")
        if str(key) != revision_id:
            raise ValueError(
                f"component mapping key {key!r} does not match revision_id "
                f"{revision_id!r}"
            )
        normalized_components[revision_id] = deepcopy(dict(value))


    missing = sorted(set(refs) - set(normalized_components))
    if missing:
        raise ValueError(
            "design references unavailable component revisions: "
            + ", ".join(missing)
        )


    scene_copy = deepcopy(dict(scene))
    electrical_copy = deepcopy(dict(electrical_design))
    if detailed_electrical_inputs is not None:
        detailed_electrical_inputs.replay()
    return CanonicalRevisionStore(
        scene_revisions={str(scene_copy["revision_id"]): scene_copy},
        electrical_revisions={
            str(electrical_copy["electrical_revision_id"]): electrical_copy
        },
        weather_revisions={str(weather.dataset["revision_id"]): weather.copy()},
        component_revisions=normalized_components,
        detailed_electrical_inputs=detailed_electrical_inputs,
    )




DESIGN_STATE_PACKAGE_FORMAT = "rawibumi.design_state_package.v0.1"
LEGACY_DESIGN_STATE_PACKAGE_FORMATS = {"opensimpv.design_state_package.v0.1"}
SUPPORTED_DESIGN_STATE_PACKAGE_FORMATS = {
    DESIGN_STATE_PACKAGE_FORMAT,
    *LEGACY_DESIGN_STATE_PACKAGE_FORMATS,
}




def persist_design_state_package(
    output_directory: str | Path,
    *,
    scene: Mapping[str, Any],
    electrical_design: Mapping[str, Any],
    project_revision: Mapping[str, Any],
    simulation_configuration: Mapping[str, Any],
    design_validation_report: Mapping[str, Any],
) -> Path:
    """Persist the exact canonical Phase-4 design state used for save/reopen.


    Weather/component payloads remain revisioned external dependencies. Their
    exact revision IDs are pinned by ProjectRevision, Scene and ElectricalDesign.
    UI workspace state is deliberately excluded.
    """
    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=True)


    objects = {
        "scene.json": deepcopy(dict(scene)),
        "electrical-design.json": deepcopy(dict(electrical_design)),
        "project-revision.json": deepcopy(dict(project_revision)),
        "simulation-configuration.json": deepcopy(dict(simulation_configuration)),
        "design-validation-report.json": deepcopy(dict(design_validation_report)),
    }
    hashes = {
        filename: canonical_object_sha256(value)
        for filename, value in objects.items()
    }
    package_sha256 = canonical_object_sha256(
        {
            "schema": DESIGN_STATE_PACKAGE_FORMAT,
            "object_sha256": hashes,
        }
    )
    manifest = {
        "schema_name": "DesignStatePackageManifest",
        "schema_version": "0.1",
        "package_format": DESIGN_STATE_PACKAGE_FORMAT,
        "project_revision_id": str(project_revision["project_revision_id"]),
        "scene_revision_id": str(scene["revision_id"]),
        "electrical_revision_id": str(
            electrical_design["electrical_revision_id"]
        ),
        "weather_dataset_revision_id": str(
            project_revision["weather_dataset_revision_id"]
        ),
        "design_validation_report_id": str(
            design_validation_report["design_validation_report_id"]
        ),
        "object_sha256": hashes,
        "package_sha256": package_sha256,
        "ui_workspace_state_included": False,
    }


    for filename, value in objects.items():
        persist_json_artifact(directory / filename, value)
    persist_json_artifact(directory / "design-state-manifest.json", manifest)
    return directory




def load_design_state_package(
    package_directory: str | Path,
) -> DesignStatePackage:
    """Load a saved canonical design package and fail closed on mutation."""
    directory = Path(package_directory)
    manifest = json.loads(
        (directory / "design-state-manifest.json").read_text(encoding="utf-8")
    )
    package_format = manifest.get("package_format")
    if package_format not in SUPPORTED_DESIGN_STATE_PACKAGE_FORMATS:
        raise ValueError("unsupported design-state package format")


    filenames = (
        "scene.json",
        "electrical-design.json",
        "project-revision.json",
        "simulation-configuration.json",
        "design-validation-report.json",
    )
    objects = {
        filename: json.loads((directory / filename).read_text(encoding="utf-8"))
        for filename in filenames
    }
    expected_hashes = manifest.get("object_sha256") or {}
    actual_hashes = {
        filename: canonical_object_sha256(value)
        for filename, value in objects.items()
    }
    if actual_hashes != expected_hashes:
        raise ValueError("design-state package object hash mismatch")


    actual_package_sha256 = canonical_object_sha256(
        {
            "schema": package_format,
            "object_sha256": actual_hashes,
        }
    )
    if actual_package_sha256 != manifest.get("package_sha256"):
        raise ValueError("design-state package manifest hash mismatch")


    scene = objects["scene.json"]
    electrical = objects["electrical-design.json"]
    project = objects["project-revision.json"]
    configuration = objects["simulation-configuration.json"]
    report = objects["design-validation-report.json"]


    if str(project.get("scene_revision_id")) != str(scene.get("revision_id")):
        raise ValueError("ProjectRevision does not pin the saved Scene revision")
    if str(project.get("electrical_revision_id")) != str(
        electrical.get("electrical_revision_id")
    ):
        raise ValueError(
            "ProjectRevision does not pin the saved ElectricalDesignRevision"
        )
    if str(configuration.get("project_revision_id")) != str(
        project.get("project_revision_id")
    ):
        raise ValueError(
            "SimulationConfiguration does not pin the saved ProjectRevision"
        )
    expected_report_identity = (
        str(project.get("project_revision_id")),
        str(scene.get("revision_id")),
        str(electrical.get("electrical_revision_id")),
    )
    actual_report_identity = (
        str(report.get("project_revision_id")),
        str(report.get("scene_revision_id")),
        str(report.get("electrical_revision_id")),
    )
    if actual_report_identity != expected_report_identity:
        raise ValueError(
            "DesignValidationReport does not match saved design revisions"
        )


    for filename, value in (
        ("project-revision.schema.json", project),
        ("simulation-configuration.schema.json", configuration),
        ("design-validation-report.schema.json", report),
    ):
        errors = _validate_schema(value, filename)
        if errors:
            raise ValueError(f"invalid saved {filename}: " + "; ".join(errors))


    return DesignStatePackage(
        scene=scene,
        electrical_design=electrical,
        project_revision=project,
        simulation_configuration=configuration,
        design_validation_report=report,
        manifest=manifest,
    )




def design_validation_gate(
    project_revision: Mapping[str, Any],
    simulation_configuration: Mapping[str, Any],
    design_validation_report: Mapping[str, Any],
    *,
    generated_at: datetime | str | None = None,
) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    """Resolve validation report identity and return run preflight evidence."""
    now = _timestamp(generated_at)
    project_revision_id = str(project_revision["project_revision_id"])
    report = deepcopy(dict(design_validation_report))
    report_id = str(
        report.get("design_validation_report_id")
        or "unresolved-design-validation-report"
    )
    findings: list[dict[str, Any]] = []


    schema_errors = _validate_schema(
        report, "design-validation-report.schema.json"
    )
    if schema_errors:
        findings.append(
            _gate_finding(
                project_revision_id=project_revision_id,
                report_id=report_id,
                rule_id="DESIGN_VALIDATION_REPORT_SCHEMA_INVALID",
                message="DesignValidationReport does not satisfy the canonical schema.",
                generated_at=now,
                context={"errors": schema_errors},
            )
        )


    expected = {
        "project_revision_id": project_revision_id,
        "scene_revision_id": str(project_revision["scene_revision_id"]),
        "electrical_revision_id": str(
            project_revision["electrical_revision_id"]
        ),
    }
    actual = {
        key: str(report.get(key) or "")
        for key in expected
    }
    identity_matches = expected == actual
    if not identity_matches:
        findings.append(
            _gate_finding(
                project_revision_id=project_revision_id,
                report_id=report_id,
                rule_id="DESIGN_VALIDATION_REPORT_REVISION_MISMATCH",
                message=(
                    "DesignValidationReport is not for the exact Project/Scene/"
                    "Electrical revisions selected for simulation."
                ),
                generated_at=now,
                context={"expected": expected, "actual": actual},
            )
        )


    if simulation_configuration.get("project_revision_id") != project_revision_id:
        findings.append(
            _gate_finding(
                project_revision_id=project_revision_id,
                report_id=report_id,
                rule_id="DESIGN_SIMULATION_CONFIGURATION_REVISION_MISMATCH",
                message=(
                    "SimulationConfiguration does not pin the ProjectRevision "
                    "validated for this launch."
                ),
                generated_at=now,
                context={
                    "configuration_project_revision_id": (
                        simulation_configuration.get("project_revision_id")
                    )
                },
            )
        )


    rule_set_matches = report.get("rule_set_id") == ENGINEERING_RULE_SET_ID
    if not rule_set_matches:
        findings.append(
            _gate_finding(
                project_revision_id=project_revision_id,
                report_id=report_id,
                rule_id="DESIGN_VALIDATION_RULE_SET_STALE",
                message=(
                    "DesignValidationReport was produced by a different "
                    "engineering-validation rule set."
                ),
                generated_at=now,
                context={
                    "required_rule_set_id": ENGINEERING_RULE_SET_ID,
                    "report_rule_set_id": report.get("rule_set_id"),
                },
            )
        )


    report_findings = [
        deepcopy(dict(item)) for item in report.get("findings", [])
    ]
    report_has_blocker = any(
        item.get("severity") == "blocking_error"
        for item in report_findings
    )
    blocking_flag = report.get("blocking_simulation") is True
    status_invalid = report.get("status") == "invalid"
    if (
        blocking_flag != report_has_blocker
        or status_invalid != report_has_blocker
    ):
        findings.append(
            _gate_finding(
                project_revision_id=project_revision_id,
                report_id=report_id,
                rule_id="DESIGN_VALIDATION_REPORT_GATE_INCONSISTENT",
                message=(
                    "DesignValidationReport status/blocking flag does not "
                    "reconcile with its blocking findings."
                ),
                generated_at=now,
                context={
                    "blocking_simulation": report.get("blocking_simulation"),
                    "status": report.get("status"),
                    "contains_blocking_finding": report_has_blocker,
                },
            )
        )


    usable_report = not schema_errors and identity_matches and rule_set_matches
    if usable_report:
        findings.extend(report_findings)
        if blocking_flag:
            findings.append(
                _gate_finding(
                    project_revision_id=project_revision_id,
                    report_id=report_id,
                    rule_id="DESIGN_VALIDATION_BLOCKS_SIMULATION",
                    message=(
                        "The exact validated design contains blocking "
                        "engineering findings and cannot enter numerical execution."
                    ),
                    generated_at=now,
                    context={
                        "design_validation_report_id": report_id,
                        "rule_set_id": report.get("rule_set_id"),
                    },
                )
            )


    evidence = {
        "design_validation_report_id": report_id,
        "design_validation_report_sha256": canonical_object_sha256(report),
        "design_validation_rule_set_id": str(report.get("rule_set_id") or ""),
        "design_validation_status": str(report.get("status") or ""),
        "blocking_simulation": bool(report.get("blocking_simulation")),
    }
    return tuple(findings), evidence




def prepare_design_simulation(
    project_revision: Mapping[str, Any],
    simulation_configuration: Mapping[str, Any],
    revision_store: CanonicalRevisionStore,
    design_validation_report: Mapping[str, Any],
    *,
    generated_at: datetime | str | None = None,
) -> DesignSimulationPreparation:
    """Freeze the Phase-4 design launch inputs before numerical execution."""
    project_copy = deepcopy(dict(project_revision))
    configuration_copy = deepcopy(dict(simulation_configuration))
    report_copy = deepcopy(dict(design_validation_report))


    for filename, value in (
        ("project-revision.schema.json", project_copy),
        ("simulation-configuration.schema.json", configuration_copy),
    ):
        errors = _validate_schema(value, filename)
        if errors:
            raise ValueError(f"invalid {filename}: " + "; ".join(errors))


    findings, evidence = design_validation_gate(
        project_copy,
        configuration_copy,
        report_copy,
        generated_at=generated_at,
    )
    return DesignSimulationPreparation(
        project_revision=project_copy,
        simulation_configuration=configuration_copy,
        revision_store=revision_store,
        design_validation_report=report_copy,
        preflight_findings=findings,
        design_validation_evidence=evidence,
    )




def run_validated_design_simulation(
    project_revision: Mapping[str, Any],
    simulation_configuration: Mapping[str, Any],
    *,
    revision_store: CanonicalRevisionStore,
    design_validation_report: Mapping[str, Any],
    output_directory: str | Path,
    simulation_run_id: str,
    engine_version: str,
    executed_at: datetime | str | None = None,
) -> CanonicalSimulationExecutionResult:
    """Run an exact Phase-4 design through the canonical simulation worker."""
    prepared = prepare_design_simulation(
        project_revision,
        simulation_configuration,
        revision_store,
        design_validation_report,
        generated_at=executed_at,
    )
    run_directory = Path(output_directory) / simulation_run_id
    if run_directory.exists() and any(run_directory.iterdir()):
        raise FileExistsError(
            "simulation run directory already contains artifacts; "
            "completed or incomplete run IDs must not be reused"
        )
    run_directory.mkdir(parents=True, exist_ok=True)
    # Persist the exact design-validation input before numerical execution so the
    # canonical run-package manifest can inventory it and still be written last.
    persist_json_artifact(
        run_directory / "design-validation-report.json",
        prepared.design_validation_report,
    )


    return run_canonical_simulation(
        prepared.project_revision,
        prepared.simulation_configuration,
        revision_store=prepared.revision_store,
        output_directory=output_directory,
        simulation_run_id=simulation_run_id,
        engine_version=engine_version,
        executed_at=executed_at,
        preflight_findings=prepared.preflight_findings,
        design_validation_evidence=prepared.design_validation_evidence,
    )
