"""Canonical detailed physics through MPPT only; no downstream loss continuation."""
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from dataclasses import dataclass
import json
from math import isclose
from pathlib import Path
from typing import Mapping

import pandas as pd

from engine.irradiance import PlaneOfArrayResult, calculate_poa, complete_irradiance
from engine.module import solve_pvsyst_module_thermal_coupling
from engine.optical import apply_iam
from engine.solar import solar_position_from_weather
from geometry.shading import (SkyDomeResolution, GroundDomeResolution,
                              sun_vector_from_azimuth_elevation)
from shading.electrical import (
    derive_electrical_region_map, evaluate_electrical_region_visibility,
    build_local_electrical_irradiance_state, collapse_local_irradiance_to_module_equivalent,
    build_phase66_series_module_operating_model, assemble_general_series_string_iv,
    assemble_parallel_mppt_iv, select_mppt_operating_point,
)
from .artifacts import (canonical_object_sha256, ElectricalIntervalStore, StoredElectricalPayload,
    electrical_payload, freeze_electrical_payload, electrical_payload_bytes)
from .detailed_inputs import prepare_execution_transport, validate_execution_transport
from .temporal import prepare_temporal_execution
from .unshaded import resolve_module_runtime_inputs, _module_runtime_properties
from shading.electrical.local_irradiance import collapse_component_irradiance
from .optics_thermal import albedo_for_index, zero_horizontal_irradiance_limit

_POA_COMPONENT_COLUMNS = {"beam":"poa_beam_w_m2", "isotropic":"poa_isotropic_w_m2", "circumsolar":"poa_circumsolar_w_m2", "horizon":"poa_horizon_w_m2", "ground":"poa_ground_diffuse_w_m2"}

POWER_ABSOLUTE_TOLERANCE_W = 1e-7
POWER_RELATIVE_TOLERANCE = 1e-9
STRING_SAMPLE_COUNT = 201
NUMERICAL_POLICY = {"string_sample_count": STRING_SAMPLE_COUNT, "string_voltage_tolerance_v": 1e-9,
    "string_current_tolerance_a": 1e-9, "string_max_iterations": 200,
    "parallel_voltage_tolerance_v": 1e-9, "parallel_current_tolerance_a": 1e-9, "parallel_power_tolerance_w": 1e-7,
    "power_absolute_tolerance_w": POWER_ABSOLUTE_TOLERANCE_W, "power_relative_tolerance": POWER_RELATIVE_TOLERANCE}
TEMPERATURE_APPROXIMATION = "whole_module_sdm_efficiency_at_area_weighted_effective_irradiance_single_temperature"


def resolved_numerical_policy(shading_configuration):
    options = shading_configuration["electrical_shading_configuration"]["scientific_options"]
    count = options.get("string_sample_count", STRING_SAMPLE_COUNT)
    if isinstance(count, bool) or not isinstance(count, int) or count < 101:
        raise ValueError("detailed string_sample_count must be an integer >= 101")
    return {**NUMERICAL_POLICY, "string_sample_count": count}


@dataclass(frozen=True, init=False)
class DetailedMPPTBackendResult:
    """Immutable canonical JSON diagnostics. replay() returns an isolated copy."""
    _canonical_payload: bytes | StoredElectricalPayload
    numerical_result_sha256: str

    def __init__(self, _canonical_payload=None, numerical_result_sha256=None, *, canonical_payload=None):
        object.__setattr__(self, "_canonical_payload", canonical_payload if canonical_payload is not None else _canonical_payload)
        object.__setattr__(self, "numerical_result_sha256", numerical_result_sha256)

    @property
    def interval_store(self):
        return self._canonical_payload.intervals if isinstance(self._canonical_payload, StoredElectricalPayload) else None

    def close(self):
        if self.interval_store is not None:
            self.interval_store.close()

    @property
    def canonical_payload(self):
        return electrical_payload_bytes(self._canonical_payload)

    @classmethod
    def freeze(cls, payload):
        raw = freeze_electrical_payload(payload)
        result = cls(raw, canonical_object_sha256(payload))
        result.replay_stream()
        return result

    def replay(self):
        """Compatibility API: an isolated, fully decoded reference payload."""
        self.replay_stream()
        return json.loads(self.canonical_payload)

    def replay_stream(self):
        """Internal validated replay with a bounded interval iterator."""
        value = electrical_payload(self._canonical_payload)
        if canonical_object_sha256(value) != self.numerical_result_sha256:
            raise ValueError("detailed numerical result hash mismatch")
        from jsonschema import Draft202012Validator, FormatChecker
        schema = json.loads((Path(__file__).resolve().parents[2] / "schemas/detailed-mppt-backend-result.schema.json").read_text())
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
        if value["schema_name"] != "DetailedMPPTBackendResult" or value["schema_version"] != "0.1":
            raise ValueError("unsupported detailed numerical result contract")
        if isinstance(self._canonical_payload, StoredElectricalPayload):
            expected = value["temporal_metadata"].get("working_interval_count")
            if expected is not None and len(value["intervals"]) != expected:
                raise ValueError("detailed result thermal/electrical interval coverage mismatch")
        previous = None
        module_ids = set(value["temperature_metadata"])
        for interval in value["intervals"]:
            start, end, evaluation = (pd.Timestamp(interval[k]) for k in ("interval_start", "interval_end", "evaluation_time"))
            if previous is not None and start != previous:
                raise ValueError("detailed result interval history is not contiguous")
            if not start < end or (end - start).total_seconds() != interval["duration_seconds"]:
                raise ValueError("detailed result evaluation/interval alignment mismatch")
            previous = end
            if set(interval["modules"]) != module_ids:
                raise ValueError("detailed result module history coverage mismatch")
            if len({m["mppt_instance_id"] for m in interval["mppts"]}) != len(interval["mppts"]):
                raise ValueError("detailed result duplicate MPPT identity")
            for mppt in interval["mppts"]:
                if mppt.get("availability") == "inactive_dark":
                    ids = mppt["combined_state"]["source_string_ids"]
                    if (not ids or mppt["selected_operating_point"] is not None or mppt["tracker_state"] is not None
                        or mppt["combined_curve"] is not None or mppt["power_w"] != 0
                        or mppt["inactive_reason"] != "no_photovoltaic_operating_point"
                        or any(interval["strings"][s]["curve"] is not None for s in ids)
                        or any(r["effective_irradiance_w_m2"] != 0 for s in ids
                            for module_id in interval["strings"][s]["state"]["source_module_ids"]
                            for r in interval["modules"][module_id]["local_irradiance"]["regions"])):
                        raise ValueError("invalid inactive_dark scientific state")
                    continue
                point = mppt["selected_operating_point"]
                if point != mppt["tracker_state"]["selected_operating_point"] or mppt["constraint_flags"] != mppt["tracker_state"]["constraint_evaluation"]:
                    raise ValueError("detailed selected state/diagnostic mismatch")
                if not isclose(point["power_w"], point["voltage_v"] * point["current_a"],
                               rel_tol=POWER_RELATIVE_TOLERANCE, abs_tol=POWER_ABSOLUTE_TOLERANCE_W):
                    raise ValueError("selected MPPT power does not equal voltage times current")
        return value

    def record(self, *, stream=False):
        return {"payload": self.replay_stream() if stream else self.replay(), "numerical_result_sha256": self.numerical_result_sha256}


def _evaluate_interval(context, timing, modules):
    validate_execution_transport(context)
    strings, mppts = context["strings"], context["mppts"]
    policy, mppt_templates = context["policy"], context["mppt_templates"]
    models = {}
    for module_id, diagnostic in modules.items():
        pinned = context["module_inputs"][module_id]
        models[module_id] = build_phase66_series_module_operating_model(pinned["topology"], diagnostic["region_map"],
            diagnostic["local_irradiance"], pinned["parameterization"], pinned["evidence"], region_solver=context["module_solvers"][module_id],
            authorization_witness=context.get("module_witnesses", {}).get(module_id))
        model = models[module_id]
        diagnostic["module_operating_model"] = {"scientific_input_sha256": model.scientific_input_sha256,
            "current_domain_ceiling_a": model.current_domain_ceiling_a, "model_id": model.model_id,
            "model_version": model.model_version}
    dark_strings = {s["string_id"] for s in strings if all(
        r["effective_irradiance_w_m2"] == 0 for m in s["module_instance_ids"]
        for r in modules[m]["local_irradiance"]["regions"])}
    string_results = {s["string_id"]: assemble_general_series_string_iv(s,
        {m: models[m] for m in s["module_instance_ids"]}, sample_count=policy["string_sample_count"])
        for s in strings if s["string_id"] not in dark_strings}
    string_records = {s: {"curve": r.curve, "state": r.state} for s, r in string_results.items()}
    for s in strings:
        if s["string_id"] in dark_strings:
            string_records[s["string_id"]] = {"curve": None, "state": {
                "availability": "inactive_dark", "power_w": 0.,
                "inactive_reason": "no_photovoltaic_operating_point",
                "source_module_ids": s["module_instance_ids"]}}

    tracker_results = []
    for mppt in mppts:
        connected = set(mppt["connected_string_ids"])
        if connected <= dark_strings:
            tracker_results.append({"mppt_instance_id": mppt["mppt_instance_id"], "mppt_index": mppt["index"],
                "availability": "inactive_dark", "inactive_reason": "no_photovoltaic_operating_point", "power_w": 0.,
                "selected_operating_point": None, "tracker_state": None, "combined_curve": None,
                "tracker_model_id": context["tracker_model_id"],
                "constraint_flags": {"operating_current_limit_known": mppt_templates[mppt["mppt_instance_id"]].get("max_operating_current_a") is not None,
                    "operating_current_above_limit": None, "evaluation_availability": "inactive_no_operating_point"},
                "combined_state": {"source_string_ids": sorted(mppt["connected_string_ids"]),
                    "source_electrical_revision_id": context["electrical_revision_id"]}})
            continue
        if connected & dark_strings:
            raise ValueError("Mixed dark/active strings on one MPPT require an explicit parallel dark-branch model")
        combined = assemble_parallel_mppt_iv(mppt, {s: string_results[s].curve for s in mppt["connected_string_ids"]},
            source_electrical_revision_id=context["electrical_revision_id"])
        tracker = select_mppt_operating_point(combined.curve,
            source_electrical_revision_id=context["electrical_revision_id"],
            mppt_operating_point_model_id=context["tracker_model_id"],
            mppt_template=mppt_templates[mppt["mppt_instance_id"]])
        tracker_results.append({"mppt_instance_id": mppt["mppt_instance_id"], "mppt_index": mppt["index"],
            "selected_operating_point": tracker.state["selected_operating_point"],
            "tracker_model_id": tracker.state["mppt_operating_point_model_id"],
            "constraint_flags": tracker.state["constraint_evaluation"], "tracker_state": tracker.state,
            "combined_curve": combined.curve, "combined_state": combined.state})
    return {**timing, "modules": modules, "strings": string_records, "mppts": tracker_results}


_INTERVAL_WORKER_CONTEXT = None


def _initialize_interval_worker(context):
    global _INTERVAL_WORKER_CONTEXT
    _INTERVAL_WORKER_CONTEXT = None
    validate_execution_transport(context)
    _INTERVAL_WORKER_CONTEXT = context


def _loss_circuit_references(context, shapes, settings, resolution=None):
    """Once-per-circuit nominal binding; mixed circuits use the pinned IV kernels."""
    from copy import deepcopy
    from engine.losses.settings import circuit_reference, resolve_detailed_losses
    from engine.losses.settings import resolve_detailed_circuit_quality
    quality = resolve_detailed_circuit_quality(resolution, context["module_inputs"])
    references, mixed = {}, []
    by_id = {s["string_id"]: s for s in context["strings"]}
    for mppt in context["mppts"]:
        strings = [by_id[sid] for sid in mppt["connected_string_ids"]]
        ids = [m for s in strings for m in s["module_instance_ids"]]
        definitions = [context["module_inputs"][m]["module"] for m in ids]
        lengths = {len(s["module_instance_ids"]) for s in strings}
        revisions = {d["revision_id"] for d in definitions}
        dispersion = resolve_detailed_losses(settings, strings=strings,
            modules={m: context["module_inputs"][m]["module"] for m in ids},
            inverter_name=str(context.get("inverter_names", {}).get(mppt["inverter_instance_id"], mppt["inverter_instance_id"])),
            mppt_name=str(mppt.get("name") or mppt["index"]))
        local_settings = settings
        if quality is not None:
            local_settings = deepcopy(settings)
            local_settings["values"]["dc_wiring_stc_fraction"] = resolution["circuits"][mppt["mppt_instance_id"]]["dc_wiring_stc_fraction"]
        reference = circuit_reference(local_settings, definitions[0], modules_in_series=len(strings[0]["module_instance_ids"]),
            parallel_strings=len(strings), mppt_index=mppt["index"])
        reference.update(dispersion)
        if quality is not None:
            mid = mppt["mppt_instance_id"]
            reference.update(mppt_instance_id=mid, inverter_instance_id=mppt["inverter_instance_id"],
                module_quality_fraction=quality[mid]["applied_module_quality_fraction"],
                dc_wiring_source=resolution["circuits"][mid]["dc_wiring_source"])
        if len(lengths) != 1 or len(revisions) != 1:
            reference.pop("modules_in_series", None)
            reference.pop("technology", None)
            reference["string_module_counts"] = {st["string_id"]: len(st["module_instance_ids"]) for st in strings}
            reference["module_technologies"] = sorted({str(d.get("technology") or "unknown") for d in definitions})
            if reference["dc_wiring_stc_fraction"] == 0:
                reference.update(method="zero_wiring_no_stc_reference_needed", reference_voltage_v=None,
                    reference_current_a=None, resistance_ohm=0., module_revision_id=None,
                    module_revision_ids=sorted(revisions))
            else:
                mixed.append(mppt)
        references[str(mppt["index"])] = reference
    if mixed:
        diagnostics = {}
        stamp = "2000-01-01T12:00:00+00:00"
        for module_id, shape in shapes.items():
            visibility = deepcopy(shape["visibility"])
            for row in visibility["inline_records"]:
                for key in ("beam_visibility_factor", "sky_visibility_factor", "ground_visibility_factor"):
                    row[key] = 1.0
            visibility["physical_result_sha256"] = canonical_object_sha256({"method": "clear_stc_reference", "map": shape["region_map"]["mapping_payload_sha256"]})
            local = build_local_electrical_irradiance_state(shape["region_map"], visibility,
                unshaded_poa={"beam_w_m2": 1000., "sky_diffuse_w_m2": 0., "ground_reflected_w_m2": 0.},
                optical_modifier={"beam": 1., "sky_diffuse": 1., "ground_reflected": 1.},
                optical_model_manifest={"model_id": "clear_stc_reference", "model_version": "0.1"},
                module_temperature_c=25., interval_start=stamp, evaluation_time=stamp)
            diagnostics[module_id] = {"region_map": shape["region_map"], "local_irradiance": local}
        result = _evaluate_interval(context, {"interval_start": stamp}, diagnostics)
        for mppt in mixed:
            state = next(m for m in result["mppts"] if m["mppt_index"] == mppt["index"])
            point = state["selected_operating_point"]
            v, i = point["voltage_v"], point["current_a"]
            if not v > 0 or not i > 0:
                raise ValueError("Detailed clear-STC circuit has no positive reference V/I")
            ref = references[str(mppt["index"])]
            ref.update(method="pinned_clear_stc_iv", module_revision_id=None, reference_voltage_v=v, reference_current_a=i,
                resistance_ohm=ref["dc_wiring_stc_fraction"] * v / i,
                module_revision_ids=sorted({context["module_inputs"][m]["module"]["revision_id"]
                    for sid in mppt["connected_string_ids"] for m in by_id[sid]["module_instance_ids"]}),
                evidence_ids=sorted({context["module_inputs"][m]["evidence"]["evidence_id"]
                    for sid in mppt["connected_string_ids"] for m in by_id[sid]["module_instance_ids"]}),
                reference_irradiance_w_m2=1000., reference_temperature_c=25.)
    return references


def _evaluate_worker_interval(timing, modules):
    from .detailed_inputs import bind_worker_result
    return bind_worker_result(_INTERVAL_WORKER_CONTEXT, _evaluate_interval(_INTERVAL_WORKER_CONTEXT, timing, modules))


def _ordered_interval_results(context, tasks, workers):
    if workers == 1:
        for timing, modules in tasks:
            yield _evaluate_interval(context, timing, modules)
        return
    pending = deque()
    executor = ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn"),
        initializer=_initialize_interval_worker, initargs=(context,))
    try:
        tasks = iter(tasks)
        for _ in range(2 * workers):
            task = next(tasks, None)
            if task is None:
                break
            pending.append(executor.submit(_evaluate_worker_interval, *task))
        while pending:
            from .detailed_inputs import accept_worker_result
            yield accept_worker_result(context, pending.popleft().result())
            task = next(tasks, None)
            if task is not None:
                pending.append(executor.submit(_evaluate_worker_interval, *task))
    finally:
        for future in pending:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)


def execute_detailed_mppt_backend(weather, *, compiled_geometry, electrical_design,
                                  module_inputs: Mapping, module_configs: Mapping,
                                  shading_configuration, mppt_templates: Mapping,
                                  scientific_input_sha256, model_resolution_metadata=None,
                                  electrical_chunk_size=None, completed_chunk=None,
                                  electrical_worker_count=1, scientific_configuration=None, frozen_selection=None):
    """Use Phase 6.3–6.8 kernels without reproducing their physics.

    Full chronological module histories feed the existing steady thermal coupling.
    Regional temperature gradients and detailed-IV feedback into heat efficiency
    are deliberately absent. Geometry never consumes a postprocessed POA source.
    """
    transport = prepare_execution_transport(module_inputs, scientific_configuration, frozen_selection)
    # Executable callers using workers > 1 need an if __name__ == "__main__" guard.
    if isinstance(electrical_worker_count, bool) or not isinstance(electrical_worker_count, int) or electrical_worker_count < 1:
        raise ValueError("electrical_worker_count must be a positive integer")
    bounded = electrical_chunk_size is not None
    if completed_chunk is not None and not bounded:
        raise ValueError("completed_chunk requires bounded electrical execution")
    intervals = ElectricalIntervalStore(electrical_chunk_size) if bounded else []
    if not module_configs or set(module_configs) != set(module_inputs):
        raise ValueError("detailed module inputs/configuration coverage mismatch")
    policy = resolved_numerical_policy(shading_configuration)
    configs = list(module_configs.values())
    if len({c.simulation_timestep_seconds for c in configs}) != 1:
        raise ValueError("detailed modules require one canonical cadence")
    temporal = prepare_temporal_execution(weather, simulation_timestep_seconds=configs[0].simulation_timestep_seconds)
    solar = solar_position_from_weather(temporal.weather, timeline=temporal.timeline,
                                       delta_t_seconds=configs[0].solar_delta_t_seconds)
    from weather.validation import run_solar_aware_weather_qc
    qc = run_solar_aware_weather_qc(temporal.weather, solar)
    if qc["status"] == "failed":
        raise ValueError("Detailed weather QC failed: " + str(qc["findings"]))
    completion = complete_irradiance(temporal.weather, solar,
                                    decomposition_model_id=configs[0].decomposition_model_id)
    index = temporal.weather.series.index
    if not index.equals(solar.frame.index) or not index.equals(completion.frame.index):
        raise ValueError("detailed solar/irradiance interval alignment mismatch")
    sky = SkyDomeResolution.from_mapping(shading_configuration["sky_dome_resolution"])
    ground = GroundDomeResolution.from_mapping(shading_configuration["ground_dome_resolution"])
    module_histories = {}
    temperature_metadata = {}
    for module_id in sorted(module_inputs):
        pinned = module_inputs[module_id].replay()
        config = module_configs[module_id]
        region_map = derive_electrical_region_map(compiled_geometry, pinned["topology"], module_instance_id=module_id)
        components_enabled = config.optics_thermal_settings is not None
        poa = calculate_poa(completion, solar, surface_tilt_deg=config.surface_tilt_deg,
                            surface_azimuth_deg=config.surface_azimuth_deg, albedo=albedo_for_index(config.optics_thermal_settings, index) if components_enabled else config.albedo,
                            model_id=config.poa_model_id, simulation_timestep_seconds=config.simulation_timestep_seconds,
                            **({"model_perez": config.perez_model, "pvsyst81_perez_coefficient_set": config.pvsyst81_perez_coefficient_set} if components_enabled else {}))
        if components_enabled:
            poa = zero_horizontal_irradiance_limit(poa, completion)
        runtime = resolve_module_runtime_inputs(config.module_definition, alpha_absorption=config.alpha_absorption,
                    iam_model_id=config.iam_model_id, iam_profile=config.iam_profile,
                    module_quality_loss_fraction=config.module_quality_loss_fraction)
        incident_frame = poa.frame.copy()
        preliminary = ElectricalIntervalStore(electrical_chunk_size) if bounded else []
        for interval_start in index:
            row = poa.frame.loc[interval_start]
            sun = solar.frame.loc[interval_start]
            evaluation = pd.Timestamp(sun["evaluation_time"]).isoformat()
            visibility = evaluate_electrical_region_visibility(compiled_geometry, region_map,
                sun_vector_xyz=sun_vector_from_azimuth_elevation(float(sun["solar_azimuth_deg"]), float(sun["solar_apparent_elevation_deg"])),
                self_shading_enabled=shading_configuration["self_shading_enabled"],
                sky_resolution=sky, ground_resolution=ground, timestamp=evaluation,
                **({"include_components": True} if components_enabled else {}))
            channels = {"beam_w_m2": float(row["poa_beam_w_m2"]),
                        "sky_diffuse_w_m2": float(row["poa_sky_diffuse_w_m2"]),
                        "ground_reflected_w_m2": float(row["poa_ground_diffuse_w_m2"])}
            component_poa = {k: float(row[column]) for k,column in _POA_COMPONENT_COLUMNS.items()} if components_enabled else None
            component_options = {"component_poa": component_poa, "component_optical_modifier": {k:1.0 for k in ("beam","sky","horizon","ground")}} if components_enabled else {}
            modifiers = {"beam": 1.0, "sky_diffuse": 1.0, "ground_reflected": 1.0}
            manifest = {"model_id": "phase69a.incident_only_no_iam", "model_version": "0.1"}
            # Temperature placeholder affects neither visibility nor channel
            # collapse; final local state is rebuilt with the coupled temperature.
            local = build_local_electrical_irradiance_state(region_map, visibility, unshaded_poa=channels,
                optical_modifier=modifiers, optical_model_manifest=manifest, module_temperature_c=25.0,
                interval_start=interval_start.isoformat(), evaluation_time=evaluation, **component_options)
            equivalent = collapse_component_irradiance(region_map, local) if components_enabled else collapse_local_irradiance_to_module_equivalent(region_map, local)
            shaded = equivalent["post_geometry_poa"]
            for column, channel in (("poa_beam_w_m2", "beam_w_m2"), ("poa_sky_diffuse_w_m2", "sky_diffuse_w_m2"),
                                    ("poa_isotropic_w_m2", "sky_diffuse_w_m2"), ("poa_ground_diffuse_w_m2", "ground_reflected_w_m2")):
                incident_frame.loc[interval_start, column] = shaded[channel]
            incident_frame.loc[interval_start, "poa_global_w_m2"] = equivalent["equivalent_incident_poa_global_w_m2"]
            if components_enabled:
                for k,column in _POA_COMPONENT_COLUMNS.items():
                    incident_frame.loc[interval_start,column] = equivalent["post_geometry_components"][k]
                incident_frame.loc[interval_start,"poa_diffuse_w_m2"] = shaded["sky_diffuse_w_m2"] + shaded["ground_reflected_w_m2"]
            preliminary.append((visibility, channels, modifiers, manifest, evaluation, component_poa) if components_enabled else (visibility, channels, modifiers, manifest, evaluation))
        if bounded:
            preliminary.seal()
        incident = PlaneOfArrayResult(frame=incident_frame, metadata=poa.metadata)
        # Evaluate IAM once on shaded incident POA. Its factors also feed the
        # regional mapper, always with the original unshaded channel source.
        optical = apply_iam(incident, model_id=runtime.iam_model_id,
                            surface_tilt_deg=config.surface_tilt_deg, profile=runtime.iam_profile)
        if config.loss_settings is not None:
            from engine.losses.soiling import apply_soiling
            optical = apply_soiling(optical, config.loss_settings)
        electrical_prethermal = ElectricalIntervalStore(electrical_chunk_size) if bounded else []
        for interval_start, prepared in zip(index, preliminary):
            visibility, channels, _, _, evaluation = prepared[:5]
            f = optical.frame.loc[interval_start]
            modifiers = {"beam": float(f["iam_beam"]), "sky_diffuse": float(f["iam_sky"]),
                         "ground_reflected": float(f["iam_ground"])}
            manifest = {"model_id": runtime.iam_model_id, "model_version": "0.1"}
            if config.loss_settings is not None:
                factor = 1 - float(f["soiling_fraction"])
                modifiers = {k: v * factor for k, v in modifiers.items()}
                manifest.update(soiling_method="monthly_post_iam", soiling_fraction=float(f["soiling_fraction"]),
                    loss_settings_sha256=config.loss_settings["settings_sha256"])
            component_options = {}
            if components_enabled:
                soil_factor = 1 - float(f["soiling_fraction"]) if config.loss_settings is not None else 1.0
                component_options = {"component_poa": prepared[5], "component_optical_modifier": {
                    "beam": float(f["iam_beam"])*soil_factor, "sky": float(f["iam_sky"])*soil_factor,
                    "horizon": float(f["iam_horizon"])*soil_factor, "ground": float(f["iam_ground"])*soil_factor}}
                manifest["component_irradiance_method"] = "separate_isotropic_circumsolar_signed_horizon"
            electrical_local = build_local_electrical_irradiance_state(region_map, visibility,
                unshaded_poa=channels, optical_modifier=modifiers, optical_model_manifest=manifest,
                module_temperature_c=25.0, interval_start=interval_start.isoformat(), evaluation_time=evaluation, **component_options)
            equivalent = collapse_component_irradiance(region_map, electrical_local) if components_enabled else collapse_local_irradiance_to_module_equivalent(region_map, electrical_local)
            if not isclose(equivalent["equivalent_effective_irradiance_w_m2"],
                           float(f["effective_irradiance_w_m2"]), rel_tol=1e-12, abs_tol=1e-9):
                raise ValueError("regional/thermal-efficiency effective irradiance mismatch")
            electrical_prethermal.append((modifiers, manifest, electrical_local, component_options) if components_enabled else (modifiers, manifest, electrical_local))
        if bounded:
            electrical_prethermal.seal()
        parameters, area, _, mass = _module_runtime_properties(config.module_definition)
        coupled = solve_pvsyst_module_thermal_coupling(incident, optical, temporal.weather,
            parameter_set=parameters, module_area_m2=area, u_c_w_m2k=config.u_c_w_m2k,
            u_v_w_m2k_per_ms=config.u_v_w_m2k_per_ms, alpha_absorption=runtime.alpha_absorption,
            thermal_model_id=config.thermal_model_id, module_unit_mass_kg_m2=mass,
            initial_module_efficiency_fraction=config.initial_module_efficiency_fraction,
            temperature_tolerance_c=config.temperature_tolerance_c, efficiency_tolerance_fraction=config.efficiency_tolerance_fraction,
            max_iterations=config.max_coupling_iterations, relaxation_factor=config.coupling_relaxation_factor,
            solver=config.module_solver,
            **({"thermal_irradiance_basis": config.optics_thermal_settings["values"]["thermal"]["irradiance_basis"]} if components_enabled else {}))
        if not coupled.thermal.frame.index.equals(index):
            raise ValueError("detailed temperature interval alignment mismatch")
        temperature_metadata[module_id] = {"approximation": TEMPERATURE_APPROXIMATION, "coupling": coupled.metadata,
            "module_quality_loss_fraction": runtime.module_quality_loss_fraction,
            "module_quality_declaration": pinned["evidence"].get("module_quality_declaration", {"relationship": "unknown"}),
            "module_quality_evidence_id": pinned["evidence"]["evidence_id"],
            "module_quality_source": runtime.metadata["module_quality_loss_fraction"]["source"],
            "module_quality_application": {
                "separate_from_parameterization": "separate_scalar_deferred_to_downstream",
                "embedded_in_parameterization": "embedded_in_parameterization_no_additional_scalar",
                "unknown": "pending_calibration_independence_not_applied",
            }[pinned["evidence"].get("module_quality_declaration", {"relationship": "unknown"})["relationship"]]}
        if components_enabled:
            temperature_metadata[module_id]["optics_input_limits"] = {k: poa.metadata[k] for k in ("zero_input_policy", "zero_input_interval_count") if k in poa.metadata}
        history = ElectricalIntervalStore(electrical_chunk_size) if bounded else []
        for interval_start, prepared, prethermal in zip(index, preliminary, electrical_prethermal):
            visibility, channels, _, _, evaluation = prepared[:5]
            modifiers, manifest, prethermal_local = prethermal[:3]
            component_options = prethermal[3] if components_enabled else {}
            # Irradiance was evaluated before the thermal solve; rebind its
            # temperature through the existing hashed-state constructor.
            local = build_local_electrical_irradiance_state(region_map, visibility, unshaded_poa=channels,
                optical_modifier=modifiers, optical_model_manifest=manifest,
                module_temperature_c=float(coupled.thermal.frame.loc[interval_start, "cell_temperature_c"]),
                interval_start=interval_start.isoformat(), evaluation_time=evaluation, **component_options)
            if local["regions"] != prethermal_local["regions"]:
                raise ValueError("temperature rebinding changed local electrical irradiance")
            history.append({"region_map": region_map, "visibility": visibility, "local_irradiance": local,
                "thermal_incident_poa_w_m2": float(incident.frame.loc[interval_start, "poa_global_w_m2"]),
                "thermal_efficiency_effective_irradiance_w_m2": float(optical.frame.loc[interval_start, "effective_irradiance_w_m2"]),
                **({"post_iam_pre_soiling_w_m2": float(optical.frame.loc[interval_start, "post_iam_pre_soiling_w_m2"]),
                    "soiling_loss_w_m2": float(optical.frame.loc[interval_start, "soiling_loss_w_m2"])} if config.loss_settings is not None else {})})
        if bounded:
            history.seal()
        module_histories[module_id] = history
        if bounded:
            preliminary.close()
            electrical_prethermal.close()
    strings = sorted((s for s in electrical_design["strings"] if s["enabled"]), key=lambda s: s["string_id"])
    assigned = [m for s in strings for m in s["module_instance_ids"]]
    if set(assigned) != set(module_inputs) or len(assigned) != len(set(assigned)):
        raise ValueError("detailed strings require exact module coverage")
    mppts = sorted((m for m in electrical_design["mppt_instances"] if m["enabled"]), key=lambda m: (m["index"], m["mppt_instance_id"]))
    assigned_strings = [s for m in mppts for s in m["connected_string_ids"]]
    if set(assigned_strings) != {s["string_id"] for s in strings} or len(assigned_strings) != len(set(assigned_strings)):
        raise ValueError("detailed MPPTs require exact string coverage")
    header = {"schema_name": "DetailedMPPTBackendResult", "schema_version": "0.1",
        "scientific_input_sha256": scientific_input_sha256, "temporal_metadata": temporal.metadata,
        "temperature_metadata": temperature_metadata, "weather_qc": qc,
        "model_resolution_metadata": model_resolution_metadata or {}, "numerical_policy": policy,
        "downstream_continuation": "unavailable_phase69a_mppt_boundary"}

    context = {**transport, "module_inputs": {m: value.replay() for m, value in module_inputs.items()},
        "module_solvers": {m: config.module_solver for m, config in module_configs.items()},
        "strings": strings, "mppts": mppts, "policy": policy,
        "mppt_templates": {m: dict(template) for m, template in mppt_templates.items()},
        "tracker_model_id": shading_configuration["electrical_shading_configuration"]["model_selections"]["mppt_operating_point_model_id"],
        "electrical_revision_id": electrical_design["electrical_revision_id"]}

    if configs[0].loss_settings is not None:
        context["inverter_names"] = {i["inverter_instance_id"]: i.get("name") or i["inverter_instance_id"]
            for i in electrical_design["inverter_instances"]}
        shapes = {m: next(iter(module_histories[m])) for m in sorted(module_histories)}
        header["loss_circuit_references"] = _loss_circuit_references(context, shapes, configs[0].loss_settings, configs[0].circuit_loss_resolution)

    histories = [iter(module_histories[m]) for m in sorted(module_histories)]
    def interval_tasks():
        for interval_start in index:
            timing = {"interval_start": interval_start.isoformat(),
                "interval_end": pd.Timestamp(temporal.timeline.frame.loc[interval_start, "interval_end"]).isoformat(),
                "duration_seconds": int(temporal.timeline.frame.loc[interval_start, "duration_seconds"]),
                "evaluation_time": pd.Timestamp(solar.frame.loc[interval_start, "evaluation_time"]).isoformat()}
            modules = {m: next(history) for m, history in zip(sorted(module_histories), histories)}
            yield timing, modules

    chunk = []
    results = _ordered_interval_results(context, interval_tasks(), electrical_worker_count)
    try:
        for record in results:
            if completed_chunk is not None:
                chunk.append(record)
            intervals.append(record)
            if completed_chunk is not None and len(chunk) == electrical_chunk_size:
                completed_chunk(DetailedMPPTBackendResult.freeze({**header, "intervals": chunk}))
                chunk.clear()
    except BaseException:
        if bounded:
            intervals.close()
            for history in module_histories.values():
                history.close()
        raise
    finally:
        results.close()
    if chunk:
        completed_chunk(DetailedMPPTBackendResult.freeze({**header, "intervals": chunk}))
        chunk.clear()
    if bounded:
        intervals.seal()
        for history in module_histories.values():
            history.close()
    return DetailedMPPTBackendResult.freeze({**header, "intervals": intervals})
