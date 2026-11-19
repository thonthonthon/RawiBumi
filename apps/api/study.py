"""Phase-6.0D browser study orchestration.

This module contains product orchestration only. Weather acquisition, engineering
validation, geometry-aware shading and electrical simulation remain in their
existing domain subsystems.
"""

from __future__ import annotations


from copy import deepcopy
from contextlib import contextmanager
from datetime import date, datetime, timezone
from functools import wraps
from pathlib import Path
import shutil
import hashlib
import json
import logging
import math

import pandas as pd
from zoneinfo import ZoneInfo
from weather.importer import detect_weather_format, read_weather_bytes, DETECTABLE_UNSUPPORTED_WEATHER_FORMATS, SUPPORTED_WEATHER_FORMATS
from weather.validation import attach_weather_qc
from threading import RLock
from typing import Any
from uuid import uuid4

from engine.simulation.shading_accuracy import (default_shading_accuracy, resolve_shading_accuracy, configure_browser_shading_accuracy)
from engine.simulation.optics_thermal import default_optics_thermal_settings, resolve_optics_thermal_settings, patch_optics_thermal_settings
from engine.simulation.optics_thermal import configure_optics_thermal
from engine.losses.settings import CircuitLossSettingsError, default_loss_settings, resolve_loss_settings
from engine.inverter import INVERTER_VOLTAGE_DEPENDENT_BOUNDED
from engine.irradiance import POA_ISOTROPIC
from engine.module import MODULE_PVSYST_SDM
from engine.optical import IAM_NONE
from engine.simulation import (
    build_design_revision_store,
    build_project_revision_from_design,
    build_simulation_configuration_from_design,
    run_validated_design_simulation,
)
from engine.solar import SOLAR_POSITION_NREL_SPA
from engine.thermal import THERMAL_PVSYST
from geometry.shading import (
    BEAM_SOLVER_ID,
    COORDINATE_BASIS,
    FACTOR_CONVENTION,
    GROUND_VISIBILITY_SOLVER_ID,
    SKY_VISIBILITY_SOLVER_ID,
    SUN_VECTOR_CONVENTION,
)
from validation.engineering import validate_engineering_design
from weather.providers import (
    FileSystemWeatherSnapshotStore,
    OpenMeteoHistoricalAdapter,
    WeatherAcquisitionRequest,
)

from jsonschema import ValidationError, Draft202012Validator

from engine.simulation.detailed_inputs import freeze_detailed_selection, DetailedInputError
from engine.simulation.detailed_dispatch import _resolve

from .detailed_results import detailed_result_fields, hydrate_run_records
from .execution_readiness import (
    _finding,
    _ordered_findings,
    design_validation_readiness_findings,
    phase5_execution_readiness,
)
from .history import design_fingerprint
from .orientation_policy import overrides as orientation_overrides, tolerance_deg as orientation_tolerance_deg, with_effective_policy
from .service import ProjectShellService
from .weather_store import FileWeatherRevisionStore
from .project_store import ProjectNotFoundError


class ProjectBusyError(RuntimeError):
    pass


MAX_WEATHER_IMPORT_BYTES = 50 * 1024 * 1024
WEATHER_FILE_IMPORT_VERSION = "1"
_MIXED_EPW_MESSAGE = ("This EPW is a typical-year file built from months of different years. That layout is not supported yet. "
    "Use a single-year file, or export the weather from PVsyst as 'PVsyst Standard' CSV.")


class WeatherImportError(ValueError):
    def __init__(self, message, code, *, status=422, **detail):
        super().__init__(message)
        self.status = status
        self.detail = {"message": message, "code": code, **detail}


def _registered_operation(method):
    @wraps(method)
    def registered(self, project_id, *args, **kwargs):
        with self._project_operation(project_id):
            return method(self, project_id, *args, **kwargs)
    return registered


def browser_electrical_configuration(request: dict[str, str]) -> dict[str, Any]:
    """Existing electrical contract, with browser engineering choices preserved."""
    from shading.electrical.module_iv import MODULE_NONUNIFORM_IV_SOLVER_ID
    from shading.electrical.string_iv import GENERAL_SERIES_STRING_IV_SOLVER_ID
    from shading.electrical.mppt_tracker import IDEAL_GLOBAL_MPPT_MODEL_ID
    from shading.electrical.parameterization import REGION_PARAMETERIZATION_MODEL_ID
    return {
        "schema_name": "ElectricalShadingConfiguration", "schema_version": "0.1",
        "contract_version": "0.1", **request,
        "thermal_state_scope": "single_module_temperature",
        "loss_accounting_boundary": "geometry_then_electrical_mismatch_then_mppt",
        "model_selections": {
            "module_electrical_model_id": MODULE_PVSYST_SDM,
            "region_parameterization_model_id": REGION_PARAMETERIZATION_MODEL_ID,
            "cell_parameterization_model_id": None,
            "bypass_model_family_id": "bypass.constant_drop.synthetic_assumption",
            "module_iv_assembly_model_id": MODULE_NONUNIFORM_IV_SOLVER_ID,
            "string_iv_assembly_model_id": GENERAL_SERIES_STRING_IV_SOLVER_ID,
            "mppt_operating_point_model_id": IDEAL_GLOBAL_MPPT_MODEL_ID,
        }, "scientific_options": {}, "execution_options": {},
    }


ENGINE_VERSION = "rawibumi-product@phase60d"


def _token(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def _validation_configuration(electrical_design: dict[str, Any] | None = None) -> dict[str, Any]:
    """The design-validation configuration; with a design (S14b), its normal-angle orientation tolerance."""
    orientation = ({"orientation_tolerance_deg": orientation_tolerance_deg(electrical_design), "orientation_comparison": "normal_angle"}
                   if electrical_design is not None else {"orientation_tolerance_deg": 0.1})
    return {
        "schema_name": "EngineeringValidationConfiguration",
        "schema_version": "0.1",
        "minimum_cell_temperature_c": -10.0,
        "maximum_cell_temperature_c": 70.0,
        "design_irradiance_w_m2": 1000.0,
        **orientation,
        "dc_ac_ratio_warning_min": None,
        "dc_ac_ratio_warning_max": None,
        "temperature_model_policy": "detailed_then_linear_fallback",
        "fallback_voltage_uncertainty_fraction": 0.05,
        "fallback_current_uncertainty_fraction": 0.05,
    }


def _phase5_options() -> dict[str, Any]:
    return {
        "simulation_timestep_seconds": 3600,
        "numerical_options": {
            "loss_settings": default_loss_settings(),
            "optics_thermal_settings": default_optics_thermal_settings(),
            "albedo": 0.20,
            "thermal": {
                "u_c_w_m2k": 20.0,
                "u_v_w_m2k_per_ms": 0.0,
            },
            "losses": {
                "module_mismatch_loss_fraction": 0.0,
                "string_mismatch_loss_fraction": 0.0,
                "dc_array_resistance_ohm": 0.0,
            },
            "coupling": {
                "initial_module_efficiency_fraction": 0.0,
                "temperature_tolerance_c": 1e-4,
                "efficiency_tolerance_fraction": 1e-8,
                "max_iterations": 25,
                "relaxation_factor": 1.0,
            },
            "module_solver": "lambertw",
        },
    }


def simulation_defaults() -> dict[str, Any]:
    """Read-only browser settings from the same options used by actual runs."""
    options = _phase5_options()
    numerical = options["numerical_options"]
    return {
        "simulation_timestep_seconds": options["simulation_timestep_seconds"],
        **{key: numerical[key] for key in ("albedo", "thermal", "losses")},
        "module_quality": {"source": "pinned_module_definition", "fallback_loss_fraction": 0.0},
        "loss_settings": resolve_loss_settings(default_loss_settings()),
        "optics_thermal_settings": resolve_optics_thermal_settings(default_optics_thermal_settings()),
        "shading_accuracy": resolve_shading_accuracy(default_shading_accuracy()),
        "not_modelled": [],
    }


def _phase5_configuration(
    project_revision: dict[str, Any],
    *,
    configuration_id: str,
    scene: dict[str, Any] | None = None,
    shading_accuracy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    accuracy_settings = default_shading_accuracy() if shading_accuracy is None else shading_accuracy
    sampling = resolve_shading_accuracy(accuracy_settings)
    options = _phase5_options()
    configuration = build_simulation_configuration_from_design(
        project_revision,
        simulation_configuration_id=configuration_id,
        simulation_timestep_seconds=options["simulation_timestep_seconds"],
        name="Phase 6.0D browser geometry-aware study",
        model_selections={
            "solar_position": SOLAR_POSITION_NREL_SPA,
            "transposition": POA_ISOTROPIC,
            "temperature": THERMAL_PVSYST,
            "module_electrical": MODULE_PVSYST_SDM,
            "inverter": INVERTER_VOLTAGE_DEPENDENT_BOUNDED,
            "iam": IAM_NONE,
        },
        loss_model_ids=["loss_ledger.staged.v0.1"],
        shading_configuration={
            "beam_method": BEAM_SOLVER_ID,
            "diffuse_method": SKY_VISIBILITY_SOLVER_ID,
            "albedo_method": GROUND_VISIBILITY_SOLVER_ID,
            "fidelity_level": "engineering",
            "sun_position_resolution_seconds": None,
            "electrical_shading_method": None,
            "geometry_contract_version": "0.1",
            "coordinate_basis": COORDINATE_BASIS,
            "sun_vector_convention": SUN_VECTOR_CONVENTION,
            "factor_convention": FACTOR_CONVENTION,
            "receiver_granularity": "module",
            # RB-4D (user, 2026-11-08): modules always shade one another, rows included; generated fields
            # were optimistic by up to 5% without it (.ai/validation/4D/REPORT.md).
            "self_shading_enabled": True,
            "cache_policy": {"mode": "exact"},
            "geometric_resolution": {
                "receiver_subdivision_u": 1,
                "receiver_subdivision_v": 1,
            },
            "sky_dome_resolution": sampling["sky_dome_resolution"],
            "ground_dome_resolution": sampling["ground_dome_resolution"],
            "model_options": {},
        },
        numerical_options=options["numerical_options"],
        output_configuration={
            "standard_timeseries": True,
            "format": "parquet",
        },
    )

    configure_optics_thermal(configuration, default_optics_thermal_settings())
    configure_browser_shading_accuracy(configuration, accuracy_settings)
    return configuration


class BrowserStudyService:
    def __init__(
        self,
        project_service: ProjectShellService,
        *,
        weather_root: str | Path,
        run_root: str | Path,
        snapshot_root: str | Path,
    ) -> None:
        self.projects = project_service
        self.weather = FileWeatherRevisionStore(weather_root)
        self.run_root = Path(run_root)
        self.projects.run_result_loader = lambda project_id, records: hydrate_run_records(records, self.run_root, project_id)
        self.snapshots = FileSystemWeatherSnapshotStore(snapshot_root)
        self.open_meteo = OpenMeteoHistoricalAdapter()
        self._operation_lock = RLock()
        self._in_progress: dict[str, int] = {}

    @contextmanager
    def _project_operation(self, project_id):
        with self._operation_lock:
            self._in_progress[project_id] = self._in_progress.get(project_id, 0) + 1
        try:
            yield
        finally:
            with self._operation_lock:
                remaining = self._in_progress[project_id] - 1
                if remaining:
                    self._in_progress[project_id] = remaining
                else:
                    del self._in_progress[project_id]

    def _require_idle(self, project_id):
        if self._in_progress.get(project_id, 0):
            raise ProjectBusyError("project has a simulation or weather acquisition in progress")

    def update_site(self, project_id, **changes):
        with self._operation_lock:
            self._require_idle(project_id)
            return self.projects.update_site(project_id, **changes)

    @staticmethod
    def _delete_target(root, target):
        if root.is_symlink() or target.is_symlink():
            raise ValueError(f"delete target {target.name} is outside storage or uses a symlink")
        try:
            resolved_root, resolved_target = root.resolve(), target.resolve()
        except (OSError, RuntimeError) as exc:
            raise ValueError(f"cannot resolve delete target {target.name}") from exc
        if resolved_target == resolved_root or not resolved_target.is_relative_to(resolved_root):
            raise ValueError(f"delete target {target.name} is outside storage or uses a symlink")
        return target

    def delete_project(self, project_id, *, confirm=None):
        store = self.projects.store
        store.validate_project_id(project_id)
        if confirm != project_id:
            raise ValueError("confirm must equal the project id exactly")
        with self._operation_lock, store._lock:
            self._require_idle(project_id)
            bundle = self._delete_target(store.root, store.path_for(project_id))
            if not bundle.exists():
                raise ProjectNotFoundError(project_id)
            if not bundle.is_file():
                raise ValueError("project bundle is not a file")
            targets = {
                "runs": self._delete_target(self.run_root, self.run_root / project_id),
                "weather": self._delete_target(self.weather.root, self.weather.root / project_id),
                "imagery": self._delete_target(self.projects.imagery.root, self.projects.imagery.root / project_id),
            }
            for target in targets.values():
                if target.exists() and not target.is_dir():
                    raise ValueError(f"delete target {target.name} is not a directory")
            removed = {}
            for name, target in targets.items():
                removed[name] = target.exists()
                if removed[name]:
                    shutil.rmtree(target)
            store.delete(project_id)
            self.projects.history.clear(project_id, "deleted")
            return {"deleted_project_id": project_id, "removed": {"bundle": True, **removed}}

    def weather_sources(self) -> list[dict[str, Any]]:
        return [
            {
                "provider_id": self.open_meteo.provider_id,
                "source_id": source_id,
                "label": self.open_meteo.source_product(source_id).display_name,
                "acquisition_type": "historical_time_series",
                "rawibumi_resource_projection_applied": False,
                "opensimpv_resource_projection_applied": False,
            }
            for source_id in self.open_meteo.supported_source_ids()
        ]

    @_registered_operation
    def acquire_weather(
        self,
        project_id: str,
        *,
        source_id: str,
        start_date: str,
        end_date: str,
        raw_response: bytes | None = None,
    ) -> dict[str, Any]:
        """Acquire provider data, or inject an explicitly synthetic test payload."""
        bundle = self.projects.get_bundle(project_id)
        if date.fromisoformat(end_date) > datetime.now(timezone.utc).date():
            raise ValueError(f"end_date {end_date} is in the future; the archive has no data for it")
        site = bundle["project"]["site"]
        weather_dataset_id = _token(f"wx-{project_id}")
        revision_id = f"{weather_dataset_id}-r1"
        request = WeatherAcquisitionRequest(
            source_id=source_id,
            latitude_deg=float(site["latitude_deg"]),
            longitude_deg=float(site["longitude_deg"]),
            elevation_m=(
                float(site["elevation_m"])
                if site.get("elevation_m") is not None
                else None
            ),
            timezone=str(site["timezone"]),
            start_date=start_date,
            end_date=end_date,
            cell_selection="land",
        )
        kwargs = dict(
            request=request,
            weather_dataset_id=weather_dataset_id,
            revision_id=revision_id,
            name=f"{source_id} for {bundle['project']['name']}",
            site_id=str(site["site_id"]),
            snapshot_store=self.snapshots,
        )
        if raw_response is None:
            result = self.open_meteo.acquire(**kwargs)
        else:
            result = self.open_meteo.parse_response(
                raw_response,
                **kwargs,
                synthetic=True,
                evidence_detail=(
                    "Synthetic provider-shaped test payload injected through "
                    "BrowserStudyService.acquire_weather(raw_response=...). "
                    "It emulates the selected Open-Meteo/ERA5 source product; "
                    "no provider retrieval or actual ERA5 observations are asserted."
                ),
            )

        selection = self.weather.save(
            project_id,
            result.weather,
            acquisition_manifest=result.manifest,
        )
        with self.projects.store._lock:
            current = self.projects.get_bundle(project_id)
            current["weather_selection"] = selection
            current["project"]["project_revision"]["weather_dataset_revision_id"] = revision_id
            self.projects.save_bundle(current, history_mode="barrier")
        return {
            "selection": selection,
            "manifest": result.manifest,
            "qc_report": result.qc_report,
        }

    @_registered_operation
    def import_weather(self, project_id: str, *, filename: str, data: bytes, dry_run=False,
                       accept_distant_location=False) -> dict[str, Any]:
        """Parse/QC without repair; commit an immutable file revision and select it."""
        with self._operation_lock:
            if self._in_progress.get(project_id, 0) != 1:
                raise ProjectBusyError("project has a simulation or weather acquisition in progress")
        bundle = self.projects.get_bundle(project_id)
        if len(data) > MAX_WEATHER_IMPORT_BYTES:
            raise WeatherImportError("Weather files must be no larger than 50 MiB.", "weather_file_too_large", status=413)
        if not data:
            raise WeatherImportError("The weather file is empty.", "weather_file_empty")
        filename = filename.replace("\\", "/").rsplit("/", 1)[-1]
        try:
            format_id = detect_weather_format(data, filename=filename)
        except (ValueError, TypeError) as exc:
            raise WeatherImportError("Unable to detect weather format. Supported formats: " +
                ", ".join(sorted(SUPPORTED_WEATHER_FORMATS)) + '. From Meteonorm or PVsyst, export the hourly weather as TMY3 or "PVsyst Standard" CSV and import that file.', "weather_format_unsupported") from exc
        if format_id in DETECTABLE_UNSUPPORTED_WEATHER_FORMATS:
            raise WeatherImportError("This is PVsyst's internal .MET format. In PVsyst, export the hourly weather as "
                "'PVsyst Standard' CSV and import that file. Direct .MET import is planned.", "pvsyst_met_not_supported")
        dataset_id = _token(f"wx-{project_id}")
        try:
            weather = read_weather_bytes(data, weather_dataset_id=dataset_id, revision_id=f"{dataset_id}-r1",
                name=f"{format_id} file {filename}", site_id=bundle["project"]["site"]["site_id"],
                filename=filename, source_format=format_id)
            json.dumps(weather.dataset, allow_nan=False)
            Draft202012Validator(json.loads((Path(__file__).resolve().parents[2] / "weather/schema/weather-dataset.schema.json").read_text())).validate(weather.dataset)
            location = weather.dataset.get("location") or {}
            for key, limit in (("latitude_deg", 90), ("longitude_deg", 180)):
                value = location.get(key)
                if value is not None and (not math.isfinite(float(value)) or abs(float(value)) > limit):
                    raise ValueError(f"invalid file {key}")
            weather, qc = attach_weather_qc(weather)
        except (ValueError, ValidationError) as exc:
            message = exc.message if isinstance(exc, ValidationError) else str(exc)
            raise WeatherImportError(f"The weather file could not be parsed: {message}", "weather_parse_failed") from exc
        except (TypeError, KeyError, IndexError, OverflowError) as exc:
            logging.getLogger(__name__).exception("Unexpected weather reader failure")
            raise WeatherImportError("The weather file could not be parsed: the file contains invalid or incomplete data.",
                                     "weather_parse_failed") from exc
        site = {key: bundle["project"]["site"].get(key) for key in ("latitude_deg", "longitude_deg", "elevation_m", "timezone")}
        warnings = []
        distance = None
        if location.get("latitude_deg") is not None and location.get("longitude_deg") is not None:
            lat1, lat2 = map(math.radians, (float(site["latitude_deg"]), float(location["latitude_deg"])))
            dlat = lat2 - lat1
            dlon = math.radians(float(location["longitude_deg"]) - float(site["longitude_deg"]))
            a = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2
            distance = 6371.0088 * 2 * math.asin(math.sqrt(min(1.0, max(0.0, a))))
            if distance > 10:
                warnings.append({"code": "weather_location_distant", "message": f"The weather file location is {distance:.1f} km from the site.", "distance_km": distance})
        else:
            warnings.append({"code": "weather_location_unknown", "message": "The file has no location. Check that this file belongs to the site."})
        if location.get("elevation_m") is not None and site.get("elevation_m") is not None:
            delta = abs(float(location["elevation_m"]) - float(site["elevation_m"]))
            if delta > 500:
                warnings.append({"code": "weather_elevation_differs", "message": f"File and site elevations differ by {delta:.0f} m.", "difference_m": delta})
        origin = weather.dataset["time_semantics"]["origin_source"]
        source_offset = origin.get("utc_offset_hours")
        instant = weather.series.index[0].to_pydatetime().astimezone(ZoneInfo(str(site["timezone"])))
        standard_offset = (instant.utcoffset() - instant.dst()).total_seconds() / 3600
        if source_offset is not None and not math.isclose(float(source_offset), standard_offset, abs_tol=1e-9):
            warnings.append({"code": "weather_timezone_differs", "message": "The file's source UTC offset differs from the site's standard offset. Timestamps are unchanged.",
                "source_offset_hours": float(source_offset), "site_offset_hours": standard_offset})
        timestamp_failure = any(f["category"] == "time" and f["severity"] in {"error", "blocking_error"} for f in qc["findings"])
        mixed_epw = format_id == "epw" and len(set(weather.series.index.year)) > 1 and timestamp_failure
        if mixed_epw:
            warnings.append({"code": "weather_typical_year_mixed_years", "message": _MIXED_EPW_MESSAGE})
        monthly = []
        for month in range(1, 13):
            if "ghi_w_m2" not in weather.series:
                monthly.append(None)
                continue
            values = weather.series.loc[weather.series.index.month == month, "ghi_w_m2"]
            monthly.append(float(values.sum()) * int(weather.dataset["series_resolution_seconds"]) / 3600000
                           if all(math.isfinite(float(v)) for v in values) else None)
        failed = qc["status"] == "failed" or any(f["severity"] in {"error", "blocking_error"} for f in qc["findings"])
        preview = {"format": format_id, "filename": filename, "sha256": hashlib.sha256(data).hexdigest(),
            "location": location or None, "site": site, "distance_km": distance,
            "time_zone": {"source_timezone": origin.get("timezone"), "source_utc_offset_hours": source_offset,
                "canonical_timezone": weather.dataset["timezone"], "site_timezone": site["timezone"], "site_standard_utc_offset_hours": standard_offset},
            "period": {"start": weather.dataset["start_time"], "end": weather.dataset["end_time"]},
            "step_minutes": weather.dataset["series_resolution_seconds"] / 60, "row_count": len(weather.series),
            "variables": list(weather.series.columns), "typical_year": weather.dataset.get("calendar_type") == "typical_year" or
                weather.dataset.get("leap_year_handling") in {"epw_8760_typical_year", "pvsyst_typical_year"},
            "monthly_ghi_kwh_m2": monthly, "annual_ghi_kwh_m2": sum(monthly) if all(v is not None for v in monthly) else None,
            "qc": {"status": qc["status"], "findings": qc["findings"]}, "warnings": warnings,
            "requires_accept_distant_location": distance is not None and distance > 50}
        if dry_run:
            return preview
        if failed:
            message = _MIXED_EPW_MESSAGE if mixed_epw else ("Weather timestamps must be continuous and increasing. Use a single-year file." if timestamp_failure
                else "Weather quality checks failed. Review the findings before importing.")
            raise WeatherImportError(message, "weather_quality_failed", findings=qc["findings"], warnings=warnings,
                **({"reason_code": "weather_typical_year_mixed_years"} if mixed_epw else {}))
        if preview["requires_accept_distant_location"] and not accept_distant_location:
            raise WeatherImportError("The weather location is more than 50 km from this site. Review the preview and explicitly accept the distance.",
                "weather_location_distant", preview=preview)
        # Per-project raw-byte deduplication retains the original immutable import evidence.
        selection = None
        for path in sorted((self.weather.root / project_id).glob("*/acquisition-manifest.json")):
            manifest = json.loads(path.read_text())
            if manifest.get("kind") == "file_import" and manifest.get("sha256") == preview["sha256"]:
                old = self.weather.load(project_id, path.parent.name).dataset
                selection = {key: old.get(key) for key in ("weather_dataset_id", "source_id", "name", "start_time", "end_time", "timezone", "data_quality_status")}
                selection.update(revision_id=old["revision_id"], manifest=manifest)
                break
        duplicate = selection is not None
        if not duplicate:
            self.snapshots.put(data, suffix=".weather")
            manifest = {"kind": "file_import", "format": format_id, "filename": filename, "sha256": preview["sha256"],
                "importer": f"weather.{format_id}", "importer_version": WEATHER_FILE_IMPORT_VERSION, "size": len(data),
                "imported_at": datetime.now(timezone.utc).isoformat(), "location": location or None, "distance_km": distance,
                "warnings": warnings, "accepted_distant_location": bool(accept_distant_location and preview["requires_accept_distant_location"])}
            selection = self.weather.save(project_id, weather, acquisition_manifest=manifest)
        with self.projects.store._lock:
            current = self.projects.get_bundle(project_id)
            current["weather_selection"] = selection
            current["project"]["project_revision"]["weather_dataset_revision_id"] = selection["revision_id"]
            self.projects.save_bundle(current, history_mode="barrier")
        return {"selection": selection, "manifest": selection["manifest"], "preview": preview, "duplicate": duplicate}

    @staticmethod
    def _simulation_electrical_snapshot(
        electrical: dict[str, Any],
        *,
        project_revision_id: str,
        snapshot_id: str,
    ) -> dict[str, Any]:
        # S14b: the run carries the effective orientation policy, so its plan groups as the checks do.
        snapshot = deepcopy(with_effective_policy(electrical))
        snapshot["electrical_revision_id"] = snapshot_id
        snapshot["revision_number"] = int(snapshot.get("revision_number") or 1) + 1
        snapshot["supersedes_revision_id"] = electrical["electrical_revision_id"]
        snapshot["status"] = "active"
        snapshot["created_by"] = "browser-study-snapshot"
        snapshot["change_summary"] = (
            "Immutable Phase-6.0D simulation snapshot with coherent project revision identity."
        )
        if "project_revision_id" in snapshot:
            snapshot["project_revision_id"] = project_revision_id
        for collection in ("inverter_instances", "strings", "connections"):
            for item in snapshot.get(collection, []):
                if "project_revision_id" in item:
                    item["project_revision_id"] = project_revision_id
        return snapshot

    def execution_readiness(self, project_id: str, electrical_request=None) -> dict[str, Any]:
        bundle = self.projects.get_bundle(project_id)
        options = _phase5_options()["numerical_options"]
        options["loss_settings"] = deepcopy(bundle.get("loss_settings", {**default_loss_settings(), "defaults_id": "recommended_defaults.v1"}))
        options["optics_thermal_settings"] = deepcopy(bundle.get("optics_thermal_settings", default_optics_thermal_settings()))
        shading_findings = []
        try:
            resolve_shading_accuracy(bundle.get("shading_accuracy", default_shading_accuracy()))
        except ValueError as exc:
            shading_findings = [_finding("SHADING_ACCURACY_INVALID", str(exc))]
        legacy = phase5_execution_readiness(bundle, numerical_options=options, detailed=electrical_request is not None)
        try:
            electrical = self._simulation_electrical_snapshot(bundle["electrical_design"],
                project_revision_id="browser-preflight", snapshot_id="browser-preflight-electrical")
            components = {**bundle["pinned_components"]["modules"], **bundle["pinned_components"]["inverters"]}
            validation = validate_engineering_design(bundle["scene"], electrical,
                project_revision_id="browser-preflight", component_revisions=components,
                configuration=_validation_configuration(electrical), design_validation_report_id="browser-preflight",
                generated_at=datetime.now(timezone.utc).isoformat())
            validation_findings = design_validation_readiness_findings(validation, orientation_overrides(bundle["electrical_design"]))
        except (ValueError, KeyError, TypeError, ValidationError) as exc:
            unavailable = _finding("DESIGN_VALIDATION_UNAVAILABLE", f"Design validation unavailable: {exc}")
            unavailable["category"] = "design_validation"
            validation_findings = [unavailable]
        legacy["findings"] = _ordered_findings([*legacy["findings"], *validation_findings, *shading_findings])
        legacy["ready"] = not any(item["severity"] == "blocking_error" for item in legacy["findings"])
        if electrical_request is None:
            return legacy
        exclusion_findings = [item for item in legacy["findings"] if item["rule_id"] == "MODULES_NOT_SIMULATED"]
        geometry_findings = [
            item for item in legacy["findings"]
            if item["rule_id"].startswith(("SCENE_", "LOSS_SETTINGS_", "OPTICS_THERMAL_", "SHADING_ACCURACY_")) or item["rule_id"] == "PV_FIELD_EMPTY"
        ]
        # Run the existing detailed/fallback decisions with their original inputs;
        # append S1 findings and enforce geometry blockers after every decision.
        original_findings = [item for item in legacy["findings"]
                             if item not in geometry_findings and item not in exclusion_findings
                             and item["category"] != "design_validation"]
        legacy = {**legacy, "findings": original_findings,
                  "ready": not any(item["severity"] == "blocking_error" for item in original_findings)}

        def with_geometry(result):
            result["findings"] = [*result["findings"], *geometry_findings, *exclusion_findings]
            if any(item["severity"] == "blocking_error" for item in geometry_findings):
                result.update(ready=False, execution_class="blocked_detailed_inputs")
            return result

        result = {**legacy, "execution_class": "blocked_detailed_inputs", "ready": False,
                  "requested_fidelity": electrical_request["requested_fidelity"],
                  "fallback_policy": electrical_request["fallback_policy"]}
        from engine.simulation.execution_groups import detailed_inverter_scope_finding
        refusal = detailed_inverter_scope_finding(bundle["scene"], bundle["electrical_design"])
        if refusal is not None:
            result["findings"] = [*legacy["findings"], _finding(refusal["rule_id"],
                refusal["message"], entity_id=refusal["entity_id"], context=refusal["context"])]
            return with_geometry(result)
        selection = bundle.get("weather_selection") or {}
        if not selection.get("revision_id"):
            result["findings"] = [item for item in legacy["findings"]
                                  if item["rule_id"] == "EXECUTION_WEATHER_REVISION_REQUIRED"]
            return with_geometry(result)
        try:
            weather = self.weather.load(project_id, selection["revision_id"])
            components = {**bundle["pinned_components"]["modules"], **bundle["pinned_components"]["inverters"]}
            electrical = self._simulation_electrical_snapshot(bundle["electrical_design"],
                project_revision_id="browser-preflight", snapshot_id="browser-preflight-electrical")
            project = build_project_revision_from_design(bundle["scene"], electrical,
                project_revision_id="browser-preflight", revision_number=1,
                weather_dataset_revision_id=bundle["weather_selection"]["revision_id"])
            validation = validate_engineering_design(bundle["scene"], electrical,
                project_revision_id="browser-preflight", component_revisions=components,
                configuration=_validation_configuration(electrical), design_validation_report_id="browser-preflight",
                generated_at=datetime.now(timezone.utc).isoformat())
            if validation.get("blocking_simulation"):
                result["findings"] = deepcopy(validation["findings"])
                return with_geometry(result)
            configuration = _phase5_configuration(project, configuration_id="browser-preflight",scene=bundle["scene"],
                shading_accuracy=bundle.get("shading_accuracy", default_shading_accuracy()))
            configuration["numerical_options"]["loss_settings"] = deepcopy(bundle.get("loss_settings", {**default_loss_settings(), "defaults_id": "recommended_defaults.v1"}))
            configure_optics_thermal(configuration, bundle.get("optics_thermal_settings", default_optics_thermal_settings()))
            configuration["shading_configuration"]["electrical_shading_configuration"] = browser_electrical_configuration(electrical_request)
            store = build_design_revision_store(bundle["scene"], electrical, weather,
                components, detailed_electrical_inputs=freeze_detailed_selection(bundle))
            _resolve(configuration, store, bundle["scene"], electrical)
            result.update(ready=True, execution_class="ready_detailed", findings=[])
        except (DetailedInputError, ValueError, KeyError, ValidationError) as exc:
            fallback = legacy["ready"] and isinstance(exc, DetailedInputError) and electrical_request["fallback_policy"] == "explicit_lower_fidelity"
            # Presentation category only: retain the backend finding verbatim.
            unsupported = isinstance(exc, DetailedInputError) and any(
                marker in str(exc) for marker in ("unsupported", "supports only", "residual semantic"))
            result.update(ready=fallback, execution_class="explicit_fallback_available" if fallback else
                ("unsupported_configuration" if unsupported else "blocked_detailed_inputs"),
                findings=[{"rule_id": "LOSS_SETTINGS_INVALID" if isinstance(exc, CircuitLossSettingsError) else "DETAILED_EXECUTION_PREFLIGHT", "severity": "warning" if fallback else "blocking_error",
                    "category": "execution", "message": str(exc)}])
        return with_geometry(result)

    @_registered_operation
    def run_study(self, project_id: str, electrical_request=None) -> dict[str, Any]:
        bundle = self.projects.get_bundle(project_id)
        # Taken from the launch snapshot: edits made while the run is in progress must not relabel it.
        launch_fingerprint = design_fingerprint(bundle)
        selection = bundle.get("weather_selection")
        if not selection or not selection.get("revision_id"):
            raise ValueError("select or acquire a weather source before simulation")

        readiness = self.execution_readiness(project_id, electrical_request)
        if readiness["ready"] is not True:
            blockers = readiness.get("findings") or []
            detail = (
                blockers[0].get("message")
                if blockers
                else "design is outside the current Phase-5 execution envelope"
            )
            raise ValueError(f"simulation execution preflight failed: {detail}")

        weather = self.weather.load(project_id, str(selection["revision_id"]))
        launched_at = datetime.now(timezone.utc).isoformat()
        run_id = _token(f"run-{project_id}")
        project_revision_id = _token(f"{project_id}-simulation-revision")
        electrical_snapshot_id = _token(
            f"{bundle['electrical_design']['electrical_revision_id']}-snapshot"
        )
        electrical = self._simulation_electrical_snapshot(
            bundle["electrical_design"],
            project_revision_id=project_revision_id,
            snapshot_id=electrical_snapshot_id,
        )

        project_revision = build_project_revision_from_design(
            bundle["scene"],
            electrical,
            project_revision_id=project_revision_id,
            revision_number=int(
                bundle["project"]["project_revision"].get("revision_number") or 1
            )
            + 1,
            weather_dataset_revision_id=str(selection["revision_id"]),
            change_summary="Phase-6.0D immutable browser simulation snapshot.",
        )
        configuration = _phase5_configuration(
            project_revision,
            configuration_id=_token(f"simcfg-{project_id}"),
            scene=bundle["scene"],
            shading_accuracy=bundle.get("shading_accuracy", default_shading_accuracy()),
        )

        configuration["numerical_options"]["loss_settings"] = deepcopy(bundle.get("loss_settings", {**default_loss_settings(), "defaults_id": "recommended_defaults.v1"}))
        configure_optics_thermal(configuration, bundle.get("optics_thermal_settings", default_optics_thermal_settings()))
        if electrical_request is not None:
            configuration["shading_configuration"]["electrical_shading_configuration"] = browser_electrical_configuration(electrical_request)

        components: dict[str, dict[str, Any]] = {}
        for kind in ("modules", "inverters"):
            components.update(deepcopy(bundle["pinned_components"].get(kind, {})))
        if not components:
            raise ValueError("simulation requires pinned module and inverter revisions")

        validation = validate_engineering_design(
            bundle["scene"],
            electrical,
            project_revision_id=project_revision_id,
            component_revisions=components,
            configuration=_validation_configuration(electrical),
            design_validation_report_id=_token(f"validation-{project_id}"),
            generated_at=launched_at,
        )
        revision_store = build_design_revision_store(
            bundle["scene"],
            electrical,
            weather,
            components,
            detailed_electrical_inputs=freeze_detailed_selection(bundle) if electrical_request is not None else None,
        )
        result = run_validated_design_simulation(
            project_revision,
            configuration,
            revision_store=revision_store,
            design_validation_report=validation,
            output_directory=self.run_root / project_id,
            simulation_run_id=run_id,
            engine_version=ENGINE_VERSION,
            executed_at=launched_at,
        )

        record = {
            "simulation_run_id": run_id,
            "status": result.simulation_run["status"],
            "project_revision_id": project_revision_id,
            "scene_revision_id": bundle["scene"]["revision_id"],
            "electrical_revision_id": electrical_snapshot_id,
            "weather_dataset_revision_id": str(selection["revision_id"]),
            "input_hash": result.simulation_run.get("input_hash"),
            "design_fingerprint": launch_fingerprint,
            "module_self_shading": bool(configuration["shading_configuration"]["self_shading_enabled"]),
            # S15 (user decision 2026-11-09): the non-blocking readiness findings the run was launched with.
            "readiness_warnings": [{key: deepcopy(item.get(key)) for key in ("rule_id", "severity", "entity_id", "message", "category")}
                                   for item in readiness.get("findings") or [] if item.get("severity") == "warning"],
            "summary_result": deepcopy(result.summary_result),
            "validation_findings": deepcopy(
                result.simulation_run.get("validation_findings") or []
            ),
            "assumptions": deepcopy(result.simulation_run.get("assumptions") or []),
            "model_manifest": deepcopy(result.simulation_run.get("model_manifest")),
            "resolved_loss_settings": deepcopy(result.backend_result.electrical.ledger.metadata.get("resolved_loss_settings")) if result.backend_result is not None else resolve_loss_settings(configuration["numerical_options"]["loss_settings"]),
            **({"circuit_loss_resolution": deepcopy(result.simulation_run["circuit_loss_resolution"])} if "circuit_loss_resolution" in result.simulation_run else {}),
            "resolved_optics_thermal_settings": deepcopy(result.simulation_run.get("resolved_optics_thermal_settings")),
            "resolved_shading_accuracy": deepcopy(result.simulation_run["resolved_shading_accuracy"]),
            "weather_source": {
                "source_id": weather.dataset.get("source_id"),
                "source_product_name": (
                    (selection.get("manifest") or {}).get("source_product_name")
                    if isinstance(selection.get("manifest"), dict)
                    else None
                ),
                "start_time": weather.dataset.get("start_time"),
                "end_time": weather.dataset.get("end_time"),
            },
        }
        if "mixed_orientation" in result.simulation_run:
            record["mixed_orientation"] = deepcopy(result.simulation_run["mixed_orientation"])
        record.update(detailed_result_fields(result.artifact_directory))
        with self.projects.store._lock:
            current = self.projects.get_bundle(project_id)
            current.setdefault("simulation_runs", []).append(record)
            self.projects.save_bundle(current, history_mode="neutral")
        return record

    def runs(self, project_id: str) -> list[dict[str, Any]]:
        bundle = self.projects.get_bundle(project_id)
        return hydrate_run_records(bundle.get("simulation_runs") or [], self.run_root, project_id)

    def csv_export_source(self, project_id: str, run_id: str, *, require_hourly: bool = True):
        """Resolve only an explicitly registered run within the requested project."""
        from reporting.exports.csv_export import load_source

        from .safe_paths import safe_component

        bundle = self.projects.get_bundle(project_id)
        safe_component(run_id, "run")
        root = self.run_root.resolve()
        project_root = (root / project_id).resolve()
        directory = (project_root / run_id).resolve()
        if (project_root == root or not project_root.is_relative_to(root)
                or directory == project_root or not directory.is_relative_to(project_root)
                or (root / project_id).is_symlink() or (project_root / run_id).is_symlink()):
            raise ValueError("run reference is outside project run storage or uses a symlink")
        saved = next((r for r in bundle.get("simulation_runs", []) if r["simulation_run_id"] == run_id), None)
        if saved is None:
            raise ValueError("run not found in the requested project")
        if saved.get("package_omitted"):
            from .project_archive import OMITTED
            raise ValueError(OMITTED)
        return load_source(directory, project_id=project_id, run_id=run_id, saved=saved,
                           require_hourly=require_hourly)

    def csv_export_schema(self, project_id: str, run_id: str) -> dict[str, Any]:
        return self.csv_export_source(project_id, run_id).schema()

    def _verified_summary(self, project_id: str, run_id: str) -> dict[str, Any]:
        """The package's summary-result.json; call only after csv_export_source has verified the package."""
        import json
        summary = json.loads((self.run_root / project_id / run_id / "summary-result.json").read_text(encoding="utf-8"))
        if summary.get("simulation_run_id") != run_id:
            raise ValueError("summary result does not belong to this run")
        return summary

    def run_series(self, project_id: str, run_id: str) -> dict[str, Any]:
        """S15: the stored hourly series as day × hour matrices and a reconciled monthly table."""
        from reporting.exports.series import run_series

        source = self.csv_export_source(project_id, run_id)
        return run_series(source, self._verified_summary(project_id, run_id))

    def csv_export(self, project_id: str, run_id: str, columns: list[str], *, formats: tuple[str, ...] = ("csv",),
                   deliverable: bool = False) -> bytes:
        from reporting.exports.csv_export import Deliverable, export_zip
        from reporting.exports.series import monthly

        source = self.csv_export_source(project_id, run_id)
        extra = None
        if deliverable:
            # Read after csv_export_source has verified every package artifact's hash.
            directory = self.run_root / project_id / run_id
            saved = next(r for r in self.projects.get_bundle(project_id).get("simulation_runs", []) if r["simulation_run_id"] == run_id)
            extra = Deliverable(
                monthly=monthly(source, self._verified_summary(project_id, run_id)),
                package_files={name: (directory / name).read_bytes()
                               for name in ("summary-result.json", "design-validation-report.json", "validation-findings.json")},
                run_record=saved,
                annual_pxx=self.annual_pxx(project_id, run_id) if self.projects.get_bundle(project_id).get("uncertainty_assumptions") is not None else None)
        return export_zip(source, columns, formats=tuple(formats), deliverable=extra)

    def free_csv_export(self, project_id: str, run_id: str) -> bytes:
        from reporting.exports.free_csv import free_csv_zip

        source = self.csv_export_source(project_id, run_id, require_hourly=False)
        ledger = self.projects.get_bundle(project_id).get("uncertainty_assumptions")
        return free_csv_zip(source, self._verified_summary(project_id, run_id),
                            annual_pxx=self.annual_pxx(project_id, run_id) if ledger is not None else None)

    def annual_pxx(self, project_id: str, run_id: str) -> dict[str, Any]:
        """UNC1: annual P50–P95 of a completed annual run's PCC energy under the project's assumption ledger.

        Unavailable states are data with reason codes, never fabricated values. The run's annual energy is treated as
        the annual mean (user decision 2026-11-09); its weather calendar type only labels the basis.
        """
        from engine.uncertainty.annual_pxx import P99_UNAVAILABLE, AnnualPxxError, annual_pxx
        from engine.simulation.artifacts import canonical_json_bytes
        from hashlib import sha256

        bundle = self.projects.get_bundle(project_id)
        saved = next((r for r in bundle.get("simulation_runs") or [] if r["simulation_run_id"] == run_id), None)
        if saved is None:
            raise ValueError("run not found in the requested project")
        ledger = bundle.get("uncertainty_assumptions")
        reasons: list[dict[str, str]] = []
        summary = {}
        if saved.get("status") not in {"completed", "completed_with_warnings"}:
            reasons.append({"code": "RUN_NOT_COMPLETED", "message": "Annual Pxx needs a completed run."})
        elif saved.get("package_omitted"):
            reasons.append({"code": "PACKAGE_OMITTED", "message": "Annual Pxx needs the run's verified result package."})
        else:
            try:
                self.csv_export_source(project_id, run_id, require_hourly=False)
                summary = self._verified_summary(project_id, run_id)
            except (FileNotFoundError, ValueError) as exc:
                if not (isinstance(exc, FileNotFoundError) or isinstance(exc.__cause__, FileNotFoundError)
                        or str(exc) == "run package is incomplete: run-package-manifest.json is absent"):
                    raise
                reasons.append({"code": "PACKAGE_OMITTED", "message": "Annual Pxx needs the run's verified result package."})
            if summary and (summary.get("annual_energy_wh") is None
                            or summary.get("period_duration_hours") not in {8760, 8784}):
                reasons.append({"code": "RUN_NOT_ANNUAL", "message": "Annual Pxx needs a run over one complete year (8,760 or 8,784 hours)."})
        if ledger is None:
            reasons.append({"code": "NO_ASSUMPTIONS", "message": "Enter at least one uncertainty term with its value, source and justification."})
        calendar = None
        try:
            revision = saved.get("weather_dataset_revision_id")
            calendar = self.weather.load(project_id, revision).dataset.get("calendar_type") if revision else None
        except Exception:  # noqa: BLE001 - the calendar only labels the basis; an unreadable dataset leaves it unknown
            calendar = None
        basis = {
            "annual_mean_basis": "typical_year_as_mean" if calendar == "typical_year" else "historical_year_as_mean",
            "weather_calendar_type": calendar,
            "mean_source": "the run's annual PCC energy (summary annual_energy_wh), treated as the annual mean",
            "mean_source_sha256": sha256(canonical_json_bytes(summary)).hexdigest() if summary else None,
        }
        view: dict[str, Any] = {
            "schema_name": "AnnualPxxView", "schema_version": "1.0", "project_id": project_id, "run_id": run_id,
            "status": "unavailable", "reasons": reasons, "basis": basis,
            "ledger_sha256": sha256(canonical_json_bytes(ledger)).hexdigest() if ledger is not None else None,
            "result": None, "P99": dict(P99_UNAVAILABLE),
            "label": {"calculation_evidence": "assumption_based", "publication_status": "model_based_estimate"},
        }
        if reasons:
            return view
        try:
            view["result"] = annual_pxx(float(summary["annual_energy_wh"]) / 1000.0, ledger)
            view["status"] = "available"
        except AnnualPxxError as exc:
            view["reasons"] = [{"code": exc.code, "message": exc.message, "path": exc.path}]
        return view

    def _registered_report_source(self, project_id, run_id, *, require_hourly=True):
        source = self.csv_export_source(project_id, run_id, require_hourly=require_hourly)
        bundle = self.projects.get_bundle(project_id)
        if bundle["project"]["project_id"] != project_id or source.project_id != project_id:
            raise ValueError("report project identity mismatch")
        saved = next((r for r in bundle.get("simulation_runs", [])
                      if r["simulation_run_id"] == run_id), None)
        if saved is None:
            raise ValueError("run not found in the requested project")
        if saved.get("status") not in {"completed", "completed_with_warnings"}:
            raise ValueError("report requires a registered completed run")
        if saved["status"] != source.run["status"]:
            raise ValueError("registered report run completion status mismatch")
        for saved_key, run_key in (
            ("project_revision_id", "project_revision_id"), ("input_hash", "input_hash"),
            ("scene_revision_id", "scene_revision_id"), ("electrical_revision_id", "electrical_revision_id"),
            ("weather_revision_id", "weather_revision_id"), ("weather_dataset_revision_id", "weather_revision_id"),
            ("engine_version", "engine_version"),
        ):
            if saved_key in saved and saved[saved_key] != source.run[run_key]:
                raise ValueError(f"registered report run identity mismatch: {saved_key}")
        if not saved.get("project_revision_id"):
            raise ValueError("registered report run has no project revision")
        return source, bundle

    def report_snapshot(self, project_id: str, run_id: str) -> dict[str, Any]:
        from reporting.exports.report_snapshot import build_report_snapshot

        source, bundle = self._registered_report_source(project_id, run_id, require_hourly=False)
        view = self.projects.project_view(project_id)
        from .catalog import catalog_summaries
        pins = view["bundle"].get("pinned_components") or {}
        view["catalog"] = catalog_summaries({"modules": pins.get("modules", {}), "inverters": pins.get("inverters", {}),
            "module_topologies": (view["bundle"].get("pinned_electrical_shading_assets") or {}).get("module_topologies", {})},
            pinned_revision_ids=[key for kind in ("modules", "inverters") for key in pins.get(kind, {}) if key.startswith("lib-")])
        saved = next(r for r in view["bundle"]["simulation_runs"] if r["simulation_run_id"] == run_id)
        fingerprint = saved.get("design_fingerprint")
        if not fingerprint or view["design_fingerprint"] != fingerprint:
            raise ValueError("earlier_design: the report needs the design that this run simulated")
        directory = self.run_root / project_id / run_id
        checks = {name: (json.loads((directory / name).read_text()) if (directory / name).is_file()
                         else {"status": "unavailable", "reason": "not_in_run_package"})
                  for name in ("design-validation-report.json", "validation-findings.json")}
        return build_report_snapshot(source, self._verified_summary(project_id, run_id), view,
            annual_pxx=self.annual_pxx(project_id, run_id) if bundle.get("uncertainty_assumptions") is not None else None,
            package_checks=checks, registered_run=saved)

    def native_pdf_document(self, project_id: str, run_id: str, *, locale: str = "en", plan_figure_png=None) -> bytes:
        """Registered package only; no client-supplied report data or HTML."""
        from reporting.exports.native_pdf import render_native_pdf, verify_report_source
        source, _ = self._registered_report_source(project_id, run_id, require_hourly=False)
        directory = self.run_root / project_id / run_id
        summary = verify_report_source(source, directory)
        snapshot = self.report_snapshot(project_id, run_id)
        # Bind a snapshot assembled by the existing service to the same verified package bytes.
        if snapshot['summary'] != summary or snapshot['identity']['package_manifest_sha256'] != source.package['manifest_payload_sha256']:
            raise ValueError('report snapshot source changed during generation')
        verify_report_source(source, directory)
        return render_native_pdf(snapshot, locale=locale, plan_figure_png=plan_figure_png)

    def run_result(self, project_id: str, run_id: str) -> dict[str, Any]:
        """Expose a persisted canonical run without launching a simulation."""
        import json
        from .safe_paths import safe_component
        bundle = self.projects.get_bundle(project_id)
        safe_component(run_id, "run")
        project_root = (self.run_root / project_id).resolve()
        directory = (project_root / run_id).resolve()
        if not project_root.is_relative_to(self.run_root.resolve()) or not directory.is_relative_to(project_root):
            raise ValueError("run reference is outside run storage")
        saved = next((r for r in bundle.get("simulation_runs", []) if r["simulation_run_id"] == run_id), {})
        if saved.get("package_omitted"):
            from .project_archive import OMITTED
            raise ValueError(OMITTED)
        fields = detailed_result_fields(directory, expected_references=saved.get("detailed_electrical_shading"))
        run = json.loads((directory / "simulation-run.json").read_text())
        if run["simulation_run_id"] != run_id:
            raise ValueError("run ID does not match verified package")
        summary_path = directory / "summary-result.json"
        return {**run, "summary_result": json.loads(summary_path.read_text()) if summary_path.exists() else None, **fields}
